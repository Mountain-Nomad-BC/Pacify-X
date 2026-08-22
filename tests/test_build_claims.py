from __future__ import annotations

import json
from pathlib import Path

from runtime.build_claims import (
    build_claim_drift,
    expected_build_claims,
    validate_build_claims,
)


ROOT = Path(__file__).resolve().parents[1]


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
