"""Regression for the skill contract-link reconciliation (V3 findings F1/F2).

V3 discovered 181 of 183 skill packages carrying a stale declared contract hash, and 180 invalid
contract links. Root cause: the migration records the digest of the package file once and returns
early when the target exists, so the declared digest is never refreshed. This campaign's
capability-map reconciliation then rewrote the package files, leaving every recorded link stale.

The tests pin the repair and the classification rule that keeps it honest.
"""

from __future__ import annotations

import json
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from scripts.reconcile_skill_contract_links import (  # noqa: E402
    _declared_contract,
    _sha,
    reconcile,
)


def test_no_skill_carries_a_stale_contract_hash() -> None:
    result = reconcile(ROOT, apply=False)
    assert result["stale_count"] == 0, result["stale"][:5]
    assert result["checked"] > 100


def test_every_checked_link_is_current() -> None:
    catalogue = tomllib.loads(
        (ROOT / "registry/skill_catalog.toml").read_text(encoding="utf-8")
    )
    rows = {str(s["id"]): s for s in catalogue["skills"]}
    for skill_dir in (ROOT / ".px/skills").iterdir():
        manifest_path = skill_dir / "contracts" / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        contracts = manifest.get("contracts")
        if not isinstance(contracts, list) or not contracts:
            # An authored contract manifest is a legitimate alternative shape.
            continue
        relative = _declared_contract(ROOT, skill_dir.name, rows[skill_dir.name])
        assert relative is not None, f"{skill_dir.name}: no canonical contract"
        assert contracts[0]["sha256"] == _sha(ROOT / relative)


def test_authored_contract_manifests_are_reported_not_failed() -> None:
    result = reconcile(ROOT, apply=False)
    authored = {entry["skill_id"] for entry in result["authored_contract_manifests"]}
    # execution-placement-decision declares runtime/decision_schema/... directly.
    assert "execution-placement-decision" in authored
    assert result["stale_count"] == 0


def test_stale_hash_is_detected_in_a_synthetic_tree(tmp_path: Path) -> None:
    """A deliberately wrong declared digest must be reported."""

    # Minimal catalogue + one skill whose manifest declares the wrong hash.
    (tmp_path / "registry" / "skill_packages").mkdir(parents=True)
    (tmp_path / "registry" / "skill_catalog.toml").write_text(
        '[[skills]]\nid = "demo-skill"\nversion = "1.0.0"\nstatus = "active"\n'
        'contract = "registry/skill_packages/demo-skill.json"\n',
        encoding="utf-8",
    )
    package = tmp_path / "registry" / "skill_packages" / "demo-skill.json"
    package.write_text('{"id": "demo-skill"}\n', encoding="utf-8")
    manifest_dir = tmp_path / ".px" / "skills" / "demo-skill" / "contracts"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "px.skill-contract-links/1.0",
                "contracts": [
                    {
                        "source": "registry/skill_packages/demo-skill.json",
                        "sha256": "0" * 64,
                        "available": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = reconcile(tmp_path, apply=False)
    assert result["stale_count"] == 1
    assert result["valid"] is False

    # Applying recomputes from canonical bytes.
    applied = reconcile(tmp_path, apply=True)
    assert applied["fixed_count"] == 1
    assert reconcile(tmp_path, apply=False)["stale_count"] == 0


def test_reconciler_does_not_weaken_the_check(tmp_path: Path) -> None:
    """A missing contract file must not be silently accepted."""

    (tmp_path / "registry").mkdir(parents=True)
    (tmp_path / "registry" / "skill_catalog.toml").write_text(
        '[[skills]]\nid = "demo-skill"\nversion = "1.0.0"\nstatus = "active"\n'
        'contract = "registry/skill_packages/demo-skill.json"\n',
        encoding="utf-8",
    )
    manifest_dir = tmp_path / ".px" / "skills" / "demo-skill" / "contracts"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "px.skill-contract-links/1.0",
                "contracts": [
                    {
                        "source": "registry/skill_packages/demo-skill.json",
                        "sha256": "0" * 64,
                        "available": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = reconcile(tmp_path, apply=True)
    # With no canonical contract file there is nothing to point at: it is reported, not accepted.
    assert "demo-skill" in result["skills_without_a_catalogue_contract"]
