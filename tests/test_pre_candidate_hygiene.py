from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.pre_candidate_hygiene import (
    _cleared_preidentity_predecessor,
    _is_preserved_evidence_reparse,
    _source_invalid_active_predecessor,
    _terminal_predecessor_intentionally_stale,
    cleanup_targets,
    quarantine,
    validate_quarantine,
)


def test_cleared_preidentity_predecessor_requires_exact_supersedable_state() -> None:
    from runtime.release_campaign import STAGES

    campaign_id = "candidate-final135"
    release = {
        "schema_version": "px.release-campaign-status/1.0",
        "valid": True,
        "campaign_id": campaign_id,
        "repair_campaign_id": "repair12",
        "state": "cleared",
        "apply_count": 0,
        "identity": None,
        "active_claim": None,
        "pre_identity_reconciliation_successor": False,
        "stages": {
            name: {"status": "pending", "claim_id": None} for name in STAGES
        },
    }

    assert _cleared_preidentity_predecessor(release, campaign_id)
    assert not _cleared_preidentity_predecessor(release, "another-campaign")
    release["apply_count"] = 1
    assert not _cleared_preidentity_predecessor(release, campaign_id)
    release["apply_count"] = 0
    release["pre_identity_reconciliation_successor"] = True
    assert not _cleared_preidentity_predecessor(release, campaign_id)


def test_source_invalid_active_predecessor_requires_exact_retained_pass_prefix() -> None:
    names = (
        "sections",
        "full_profile",
        "validate",
        "package",
        "install",
        "installed_operational",
        "certify",
    )
    campaign_id = "candidate-final131"
    release = {
        "valid": True,
        "campaign_id": campaign_id,
        "state": "active",
        "apply_count": 1,
        "identity": {"release_identity_sha256": "a" * 64},
        "active_claim": None,
        "stages": {
            name: {"status": "passed" if index < 4 else "pending"}
            for index, name in enumerate(names)
        },
    }
    invalid_source = {"valid": False, "errors": ["source identity changed"]}

    assert _source_invalid_active_predecessor(
        release, invalid_source, campaign_id
    )
    assert not _source_invalid_active_predecessor(
        release, {"valid": True, "errors": []}, campaign_id
    )
    release["active_claim"] = {"claim_id": "live"}
    assert not _source_invalid_active_predecessor(
        release, invalid_source, campaign_id
    )
    release["active_claim"] = None
    release["stages"]["validate"]["status"] = "failed"
    assert not _source_invalid_active_predecessor(
        release, invalid_source, campaign_id
    )


def test_preserved_evidence_reparse_is_explained_but_product_reparse_is_not(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"

    assert _is_preserved_evidence_reparse(
        root,
        root / ".engineering-bootstrap/diagnostics/retained-workspaces/link",
    )
    assert not _is_preserved_evidence_reparse(root, root / "runtime/link")


def test_exact_terminal_predecessor_accepts_only_intact_stale_group_receipts() -> None:
    rows = [
        {"group": "passed-before-change", "passed": True, "fresh": False, "current": False},
        {"group": "failed-predecessor", "passed": False, "fresh": False, "current": False},
    ]

    assert _terminal_predecessor_intentionally_stale(True, rows)
    assert not _terminal_predecessor_intentionally_stale(False, rows)
    assert not _terminal_predecessor_intentionally_stale(
        True, [{"group": "missing-receipt", "passed": None, "fresh": False, "current": False}]
    )
    assert _terminal_predecessor_intentionally_stale(
        True,
        [{"section": "testing-governance", "passed": True, "fresh": False, "current": False}],
        identity_key="section",
    )


def test_cleanup_denominator_preserves_durable_tmp_evidence_and_release_custody(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "repo"
    temp = tmp_path / "system-temp"
    (root / ".tmp/audit_walks_plans").mkdir(parents=True)
    (root / ".tmp/ledger-payloads").mkdir()
    (root / ".tmp/pytest-repair").mkdir()
    (root / ".pytest_cache").mkdir()
    (temp / "pacify-x-final111-proof").mkdir(parents=True)
    (temp / "pacify-x-release-wheelhouse-0.7.0-final68").mkdir()
    monkeypatch.setenv("TEMP", str(temp))

    targets, preserved = cleanup_targets(root)
    displays = {item["display_path"] for item in targets}

    assert ".tmp/pytest-repair" in displays
    assert ".pytest_cache" in displays
    assert str(temp / "pacify-x-final111-proof") in displays
    assert ".tmp/audit_walks_plans" not in displays
    assert ".tmp/ledger-payloads" not in displays
    assert any("release-wheelhouse" in item["path"] for item in preserved)


def test_quarantine_is_recoverable_hash_bound_and_validated_before_delete(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "repo"
    temp = tmp_path / "system-temp"
    cache = root / ".pytest_cache/v/cache"
    cache.mkdir(parents=True)
    (cache / "nodeids").write_text("[]", encoding="utf-8")
    external = temp / "pacify-x-pytest-owned"
    external.mkdir(parents=True)
    (external / "result.txt").write_text("passed", encoding="utf-8")
    monkeypatch.setenv("TEMP", str(temp))
    manifest = Path("evidence/release/pre-candidate-quarantine-manifest.json")

    receipt = quarantine(root, manifest, run_id="unit-hygiene")

    assert receipt["valid"] is True
    assert not (root / ".pytest_cache").exists()
    assert not external.exists()
    assert (root / ".quarantine/unit-hygiene/workspace/.pytest_cache").is_dir()
    assert (root / ".quarantine/unit-hygiene/external-temp/pacify-x-pytest-owned").is_dir()
    with patch(
        "runtime.resource_lifecycle.resource_status",
        return_value={
            "valid": True,
            "active_processes": 0,
            "active_paths": 0,
            "cleanup_failures": 0,
        },
    ):
        validation = validate_quarantine(root, manifest)
    assert validation["valid"] is True
    assert validation["all_items_no_longer_needed"] is True
    persisted = json.loads((root / manifest).read_text(encoding="utf-8"))
    assert len(persisted["records"][0]["evidence"]["tree_sha256"]) == 64


def test_quarantine_validation_rejects_restored_original(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "repo"
    temp = tmp_path / "system-temp"
    target = root / ".pytest_cache"
    target.mkdir(parents=True)
    monkeypatch.setenv("TEMP", str(temp))
    temp.mkdir()
    manifest = Path("evidence/release/pre-candidate-quarantine-manifest.json")
    quarantine(root, manifest, run_id="unit-hygiene")
    target.mkdir()

    with patch(
        "runtime.resource_lifecycle.resource_status",
        return_value={
            "valid": True,
            "active_processes": 0,
            "active_paths": 0,
            "cleanup_failures": 0,
        },
    ):
        validation = validate_quarantine(root, manifest)
    assert validation["valid"] is False
    assert any("original target still exists" in error for error in validation["errors"])
