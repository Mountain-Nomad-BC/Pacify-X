from __future__ import annotations

import json
from pathlib import Path

from runtime.build_claims import (
    _registry_artifact_count,
    build_claim_drift,
    expected_build_claims,
    update_readme_claims,
    validate_build_claims,
)


ROOT = Path(__file__).resolve().parents[1]


def test_registry_claim_ignores_live_hidden_lock(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "owner.json").write_text("{}\n", encoding="utf-8")
    (registry / ".operational-gap-ledger.lock").write_text(
        "host-local\n", encoding="utf-8"
    )

    assert _registry_artifact_count(tmp_path) == 1


def test_apply_builder_computes_before_creating_its_prepared_file() -> None:
    source = ROOT / "scripts" / "build_claims.py"
    text = source.read_text(encoding="utf-8")
    assert text.index("claims = expected_build_claims(root)") < text.index(
        'temporary = target.with_name(f".{target.name}.prepared")'
    )


def test_checked_in_build_claims_and_readme_are_current() -> None:
    report = validate_build_claims(ROOT)
    assert report["valid"] is True, report["errors"]
    claims = report["claims"]
    assert claims["version"] == "0.7.0.dev0"
    assert claims == expected_build_claims(ROOT)


def test_stored_claim_drift_is_rejected(tmp_path: Path) -> None:
    expected = expected_build_claims(ROOT)
    drifted = json.loads(json.dumps(expected))
    drifted["counts"]["skills"] += 1
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/build_claims.json").write_text(
        json.dumps(drifted), encoding="utf-8"
    )
    assert build_claim_drift(drifted, expected) == [
        "stored build claims differ from canonical source facts"
    ]


def test_readme_build_claim_projection_has_one_canonical_owner(tmp_path: Path) -> None:
    labels = (
        "Runtime modules",
        "Contracts",
        "Registry artifacts",
        "Tool and support scripts",
    )
    (tmp_path / "README.md").write_text(
        "\n".join(f"| {label} | 0 |" for label in labels) + "\n",
        encoding="utf-8",
    )
    claims = {
        "counts": {
            "runtime_modules": 1,
            "contracts": 2,
            "registry_artifacts": 3,
            "tool_and_support_scripts": 4,
        }
    }
    update_readme_claims(tmp_path, claims)
    assert (tmp_path / "README.md").read_text(encoding="utf-8").splitlines() == [
        "| Runtime modules | 1 |",
        "| Contracts | 2 |",
        "| Registry artifacts | 3 |",
        "| Tool and support scripts | 4 |",
    ]
