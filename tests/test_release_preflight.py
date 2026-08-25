import json
from pathlib import Path

import runtime.release_preflight as release_preflight

from runtime.evidence_portability import (
    PRODUCT_STRUCTURED_ROOTS,
    discover_historical_references,
)
from runtime.release_preflight import (
    _cache_inputs,
    _binding,
    _canonical,
    _sha_bytes,
    installed_equivalence,
    rebuild_equivalence,
    receipt_path,
    require_stable_source_binding,
    skip_policy_preflight,
    transaction_simulation,
    validate_preflight_receipt,
    RESOURCE_REGISTRY,
)
from runtime.repository_scope import is_external_environment_relative


def test_unknown_release_skip_fails_closed(tmp_path: Path) -> None:
    junit = tmp_path / "report.xml"
    junit.write_text(
        '<testsuites><testsuite><testcase classname="x" name="y"><skipped message="unknown" /></testcase></testsuite></testsuites>'
    )
    result = skip_policy_preflight(junit)
    assert not result["valid"] and result["failures"][0]["code"] == "RP-SKP-001"


def test_finalizer_admission_requires_exact_current_binding(
    tmp_path: Path, monkeypatch
) -> None:
    binding = {
        "release": "1.0.0",
        "source_revision": "a",
        "product_digest": "b",
        "engine_identity": "c",
        "engine_manifest_sha256": "d",
        "policy_digest": "e",
        "implementation_digest": "f",
        "platform": "windows",
        "python": "3.14",
        "source_identity_valid": True,
        "product_valid": True,
        "engine_valid": True,
        "artifact_sha256": None,
    }
    monkeypatch.setattr(
        "runtime.release_preflight._binding", lambda root, release, artifact: binding
    )
    denied = validate_preflight_receipt(tmp_path, "1.0.0")
    assert not denied["valid"] and denied["code"] == "RELEASE_PREFLIGHT_REQUIRED"
    path = receipt_path(tmp_path, "1.0.0")
    path.parent.mkdir(parents=True)
    receipt = {"valid": True, "ready_for_certification": True, "binding": binding}
    receipt["receipt_sha256"] = _sha_bytes(_canonical(receipt))
    path.write_text(json.dumps(receipt))
    assert validate_preflight_receipt(tmp_path, "1.0.0")["valid"]
    binding["product_digest"] = "changed"
    assert not validate_preflight_receipt(tmp_path, "1.0.0")["valid"]


def test_preflight_receipt_tampering_fails_closed(tmp_path: Path, monkeypatch) -> None:
    binding = {
        "release": "1.0.0",
        "source_revision": "a",
        "product_digest": "b",
        "engine_identity": "c",
        "engine_manifest_sha256": "d",
        "policy_digest": "e",
        "implementation_digest": "f",
        "platform": "windows",
        "python": "3.14",
        "source_identity_valid": True,
        "product_valid": True,
        "engine_valid": True,
        "artifact_sha256": None,
    }
    monkeypatch.setattr(
        "runtime.release_preflight._binding", lambda root, release, artifact: binding
    )
    receipt = {"valid": True, "ready_for_certification": True, "binding": binding}
    receipt["receipt_sha256"] = _sha_bytes(_canonical(receipt))
    receipt["ready_for_certification"] = False
    path = receipt_path(tmp_path, "1.0.0")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(receipt))
    result = validate_preflight_receipt(tmp_path, "1.0.0")
    assert not result["valid"] and not result["receipt_integrity"]


def test_transaction_simulation_keeps_product_immutable(
    tmp_path: Path, monkeypatch
) -> None:
    clean = tmp_path / "product"
    clean.mkdir()
    (clean / "source.py").write_text("VALUE = 1\n")
    monkeypatch.setattr(
        "runtime.release_preflight.classify_tree",
        lambda root: {
            "valid": True,
            "product_digest": _sha_bytes((root / "source.py").read_bytes()),
        },
    )
    result = transaction_simulation(clean, tmp_path / "custody")
    assert result["valid"]
    assert result["product_digest_before"] == result["product_digest_after"]
    assert not (clean / "release-evidence").exists()


def test_stale_clean_projection_fails_before_finalizer(
    tmp_path: Path, monkeypatch
) -> None:
    projection = tmp_path / "registry/projection.json"
    projection.parent.mkdir()
    projection.write_text('{"value": 1}\n')

    def mutate(root: Path) -> None:
        (root / "registry/projection.json").write_text('{"value": 2}\n')

    monkeypatch.setattr(
        "scripts.clean_source_export._rebuild_candidate_projections", mutate
    )
    result = rebuild_equivalence(
        tmp_path, tmp_path / "unused", ["registry/projection.json"]
    )
    assert not result["valid"]
    assert result["failures"][0]["code"] == "RP-GEN-001"


def test_excluded_evidence_does_not_change_clean_product_projection(
    tmp_path: Path, monkeypatch
) -> None:
    registry = tmp_path / "registry/historical_external_references.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"reference_count":0,"records":[]}\n', encoding="utf-8")
    evidence = tmp_path / "evidence/operator-capture.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        '{"source":"C:\\\\Users\\\\operator\\\\outside.json"}\n',
        encoding="utf-8",
    )

    def rebuild(root: Path) -> None:
        records = discover_historical_references(
            root, structured_roots=PRODUCT_STRUCTURED_ROOTS
        )
        (root / "registry/historical_external_references.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "reference_count": len(records),
                    "records": records,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    rebuild(tmp_path)
    monkeypatch.setattr(
        "scripts.clean_source_export._rebuild_candidate_projections", rebuild
    )
    result = rebuild_equivalence(
        tmp_path,
        tmp_path / "unused",
        ["registry/historical_external_references.json"],
    )
    assert result["valid"], result["differences"]


def test_stale_installed_identity_or_missing_custody_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "runtime.evidence_index.build_index",
        lambda root, artifacts: {
            "engine_identity": {"valid": True},
            "blocking_reasons": [
                "Required win32 installed-VSIX smoke does not bind the current exact artifact and engine manifest.",
                "Required linux installed-VSIX smoke evidence is missing.",
            ],
            "records": [
                {
                    "kind": "installed-vsix-smoke",
                    "platform": "win32",
                    "artifact_bound": False,
                }
            ],
            "limitations": [],
        },
    )
    result = installed_equivalence(tmp_path)
    assert not result["valid"]
    assert result["failures"][0]["code"] == "RP-INS-001"
    assert len(result["blocking_reasons"]) == 2


def test_dependency_aware_cache_does_not_invalidate_unrelated_checks() -> None:
    binding = {
        "release": "1.0.0",
        "implementation_digest": "implementation",
        "platform": "windows",
        "python": "3.14",
        "product_digest": "product-a",
        "engine_identity": "engine",
        "engine_manifest_sha256": "manifest",
        "artifact_sha256": "artifact",
        "node": "v24",
        "policy_digest": "policy",
        "test_topology_digest": "topology-a",
    }
    installed_before = _cache_inputs("installed_equivalence", binding)
    fixed_before = _cache_inputs("fixed_point", binding)
    binding["test_topology_digest"] = "topology-b"
    assert _cache_inputs("installed_equivalence", binding) == installed_before
    assert _cache_inputs("fixed_point", binding) != fixed_before


def test_deep_discovery_exhausts_checks_without_relaxing_certification_binding(
    tmp_path: Path, monkeypatch
) -> None:
    observed = {}

    def fake_run(root: Path, **kwargs):
        observed.update(kwargs)
        return {"valid": True, "ready_for_certification": False}

    monkeypatch.setattr(release_preflight, "run_preflight", fake_run)

    result = release_preflight.run_discovery(tmp_path, release="1.0.0")

    assert result["valid"] is True
    assert result["ready_for_certification"] is False
    assert observed["deep"] is True
    assert observed["write_receipt"] is False
    assert observed["enforce_release_binding"] is False


def test_preflight_resource_ledger_is_outside_product_custody() -> None:
    assert is_external_environment_relative(RESOURCE_REGISTRY)


def test_preflight_detects_its_own_product_feedback() -> None:
    boundary = {
        "valid": True,
        "digest_comparison": {"source": "after", "clean": "after", "equal": True},
        "failures": [],
    }
    result = require_stable_source_binding(boundary, "before")
    assert not result["valid"]
    assert result["failures"][0]["code"] == "RP-MUT-001"


def test_preflight_binding_uses_exact_git_commit_sha(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies/release-preflight.json").write_text("{}\n")
    monkeypatch.setattr(
        "runtime.release_preflight.classify_tree",
        lambda root: {"valid": True, "product_digest": "product"},
    )
    monkeypatch.setattr(
        "runtime.release_preflight.validate_engine_identity",
        lambda root: {
            "valid": True,
            "tree_sha256": "engine",
            "manifest_sha256": "manifest",
        },
    )
    monkeypatch.setattr(
        "runtime.release_preflight.capture_git_identity",
        lambda root, version: {"valid": True, "commit_sha": "a" * 40},
    )
    assert _binding(tmp_path, "1.0.0", None)["source_revision"] == "a" * 40
