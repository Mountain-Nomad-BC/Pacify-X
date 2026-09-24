"""Tests for the release supply-chain artifacts and licence inventory.

Covers the WS-6 compliance tooling:

  * SBOM is generated from the actual manifests, not a hand-maintained list;
  * build provenance binds source identity and artifact hashes;
  * git-history and packaged-artifact secret scans run and agree with the invariant scanner;
  * the licence inventory matches the dependency manifests in both directions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import scripts.build_release_artifacts as artifacts  # noqa: E402
import scripts.verify_license_inventory as inventory  # noqa: E402

ROOT = Path(__file__).parents[1]


# ---------------------------------------------------------------------------
# SBOM
# ---------------------------------------------------------------------------


def test_sbom_is_derived_from_the_manifests() -> None:
    sbom = artifacts.build_sbom(ROOT)
    names = {c["name"] for c in sbom["components"]}
    assert "PyYAML" in names
    assert "zod" in names
    assert "@modelcontextprotocol/server" in names
    assert "pyproject.toml" in sbom["manifest_provenance"]
    assert "extension/package.json" in sbom["manifest_provenance"]


def test_sbom_does_not_claim_non_distributed_components() -> None:
    # Weights and the locally-built runtime are not distributed by Pacify-X and must not appear as
    # SBOM components, because claiming them would misrepresent the supply chain.
    sbom = artifacts.build_sbom(ROOT)
    component_names = {c["name"].casefold() for c in sbom["components"]}
    assert "llama.cpp" not in component_names
    assert not any("gguf" in name for name in component_names)
    assert "not SBOM components" in sbom["scope_note"]


def test_sbom_components_carry_required_fields() -> None:
    sbom = artifacts.build_sbom(ROOT)
    for component in sbom["components"]:
        assert component["name"]
        assert component["version"]
        assert component["type"] in {"application", "library"}
        assert component["scope"] in {"self", "direct", "development"}


def test_sbom_is_deterministic_except_the_timestamp() -> None:
    first = artifacts.build_sbom(ROOT)
    second = artifacts.build_sbom(ROOT)
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_provenance_records_source_and_artifact_hashes() -> None:
    provenance = artifacts.build_provenance(ROOT)
    assert provenance["schema_version"] == artifacts.PROVENANCE_SCHEMA
    assert provenance["toolchain"]["python"]
    for record in provenance["artifacts"]:
        assert len(record["sha256"]) == 64
        assert record["size_bytes"] > 0
    # The freeze rule must be stated: post-freeze generation invalidates certification.
    assert "before the certification freeze" in provenance["freeze_rule"]


def test_provenance_binds_the_local_runtime_identity_when_present() -> None:
    runtime = artifacts.build_provenance(ROOT)["local_runtime"]
    # The runtime is either absent (no build on this machine) or fully identified.
    if runtime["resolved_commit"]:
        assert len(runtime["resolved_commit"]) == 40
        assert runtime["server_sha256"]


# ---------------------------------------------------------------------------
# Secret scans
# ---------------------------------------------------------------------------


def test_git_history_scan_reports_zero_findings_when_performed() -> None:
    result = artifacts.scan_git_history(ROOT)
    if not result["performed"]:
        return  # git unavailable in this environment
    assert result["finding_count"] == 0, result["findings"][:5]


def test_secret_shapes_agree_with_the_release_invariant_scanner() -> None:
    # The two scanners must not disagree about what a credential looks like.
    import scripts.verify_release_invariants as invariants

    sample = 'api_key = "sk-abcdefghijklmnopqrstuvwxyz012345"'
    build_hit = any(p.search(sample) for p in artifacts.SECRET_SHAPES)
    invariant_hit = any(p.search(sample) for p in invariants.SECRET_SHAPES)
    assert build_hit is True
    assert invariant_hit is True


def test_packaged_scan_is_clean() -> None:
    assert artifacts.scan_packaged(ROOT)["finding_count"] == 0


# ---------------------------------------------------------------------------
# Licence inventory
# ---------------------------------------------------------------------------


def test_license_inventory_matches_the_manifests() -> None:
    result = inventory.verify(ROOT)
    assert result["valid"], {
        "missing_documents": result["missing_documents"],
        "undocumented_components": result["undocumented_components"],
    }


def test_every_manifest_dependency_is_documented() -> None:
    components = inventory.manifest_components(ROOT)
    notice = (ROOT / inventory.NOTICE).read_text(encoding="utf-8-sig")
    for name in components["python"] + components["npm"]:
        assert name in notice, f"{name} is not documented in {inventory.NOTICE}"


def test_manifest_component_extraction_sees_both_ecosystems() -> None:
    components = inventory.manifest_components(ROOT)
    assert components["python"], "python dependencies must be discovered"
    assert components["npm"], "npm dependencies must be discovered"


def test_undocumented_component_is_detected(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\ndependencies = ["totally-missing-package==1.0"]\n',
        encoding="utf-8",
    )
    (tmp_path / "THIRD_PARTY_NOTICES.md").write_text("# notices\n\nnothing here\n", encoding="utf-8")
    (tmp_path / "MODEL_AND_DATA_LICENSES.md").write_text("# models\n", encoding="utf-8")
    result = inventory.verify(tmp_path)
    assert result["valid"] is False
    assert "totally-missing-package" in result["undocumented_components"]


def test_missing_notice_document_is_detected(tmp_path: Path) -> None:
    result = inventory.verify(tmp_path)
    assert result["valid"] is False
    assert inventory.NOTICE.as_posix() in result["missing_documents"]


def test_shipped_release_artifacts_exist_and_are_valid_json() -> None:
    # The generated compliance artifacts must be present and parseable before the freeze.
    base = ROOT / "evidence/release/compliance"
    for name in ("sbom.json", "build-provenance.json", "secret-scan-git-history.json", "secret-scan-packaged.json"):
        path = base / name
        assert path.is_file(), f"{name} must be generated before the freeze"
        json.loads(path.read_text(encoding="utf-8"))