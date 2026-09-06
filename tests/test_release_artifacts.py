from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

import pytest

from runtime.release_artifacts import (
    classify_tree,
    materialize_release_source,
    verify_frozen_product,
)
from runtime.release_campaign import (
    ReleaseCampaignBlocked,
    apply_release_identity,
    claim_release_stage,
    clear_release_identity,
    finish_release_stage,
    rewind_failed_release_campaign_repair,
    rewind_invalid_release_identity_reconciliation,
    supersede_invalid_active_release_campaign,
    supersede_invalid_release_identity,
)


ROOT = Path(__file__).parents[1]
DECLARED_PACKAGED_EVIDENCE = (
    "evidence/archive-catalog.json",
    "evidence/bundles/archive-custody-20260803/manifest.json",
    "evidence/bundles/archive-custody-20260803/complete_file_inventory.jsonl",
    "evidence/capability-mining-receipt.json",
    "evidence/contract-disposition-receipt.json",
    "evidence/corpus-intake-receipt.json",
    "evidence/domain-reference-receipt.json",
    "evidence/external-source-admission-receipt.json",
    "evidence/process-audit-intake-receipt.json",
    "evidence/source-corpus-completeness.json",
    "evidence/source-intake-receipt.json",
    "evidence/source-migration-receipt.json",
)


def _minimal_tree() -> Path:
    root = Path(tempfile.mkdtemp()) / "framework"
    (root / "policies").mkdir(parents=True)
    shutil.copy2(
        ROOT / "policies/release-artifact-policy.json",
        root / "policies/release-artifact-policy.json",
    )
    (root / "runtime").mkdir()
    (root / "runtime/module.py").write_text("VALUE = 1\n", encoding="utf-8")
    return root


def test_product_digest_is_deterministic_and_detects_mutation() -> None:
    root = _minimal_tree()
    first = classify_tree(root)
    second = classify_tree(root)
    assert first["valid"] and first["product_digest"] == second["product_digest"]
    (root / "runtime/module.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert not verify_frozen_product(root, first)["valid"]


def test_unclassified_root_file_fails_closed() -> None:
    root = _minimal_tree()
    (root / "mystery.bin").write_bytes(b"unknown")
    result = classify_tree(root)
    assert not result["valid"]
    assert any("unclassified" in item for item in result["errors"])


def test_executable_payload_cannot_hide_in_evidence() -> None:
    root = _minimal_tree()
    (root / "evidence").mkdir()
    (root / "evidence/hidden.py").write_text("print('hidden')\n", encoding="utf-8")
    result = classify_tree(root)
    assert not result["valid"]
    assert result["product_valid"]
    assert any("evidence payload" in item for item in result["errors"])


def test_standard_sha256sums_manifest_is_admitted_as_non_executable_evidence() -> None:
    root = _minimal_tree()
    (root / "evidence").mkdir()
    manifest = root / "evidence/audit/SHA256SUMS"
    manifest.parent.mkdir()
    manifest.write_text(f"{'a' * 64}  receipt.json\n", encoding="utf-8")

    result = classify_tree(root)

    record = next(item for item in result["records"] if item["path"] == "evidence/audit/SHA256SUMS")
    assert result["valid"], result["errors"]
    assert record["classification"] == "evidence_output"
    assert record["sha256"] is None


def test_only_evidence_change_does_not_change_product_digest() -> None:
    root = _minimal_tree()
    (root / "evidence").mkdir()
    evidence = root / "evidence/result.json"
    evidence.write_text("{}\n", encoding="utf-8")
    first = classify_tree(root)
    evidence.write_text('{"changed":true}\n', encoding="utf-8")
    second = classify_tree(root)
    assert first["product_digest"] == second["product_digest"]


def test_live_test_orchestration_lock_is_control_output_not_product() -> None:
    root = _minimal_tree()
    lock = root / ".engineering-bootstrap/test-evidence/.test-orchestration.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text('{"owner":"active-test-profile"}\n', encoding="utf-8")

    result = classify_tree(root)

    record = next(item for item in result["records"] if item["path"] == lock.relative_to(root).as_posix())
    assert result["valid"], result["errors"]
    assert record["classification"] == "control_output"
    assert record["sha256"] is None


def test_host_local_probe_and_lock_recovery_receipts_are_excluded_from_release() -> None:
    root = _minimal_tree()
    paths = (
        ".px/mcp-runtime-probe.json",
        "registry/.lock-recovery-receipts/.operational-gap-ledger.lock/receipt.json",
    )
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("C:" + "/Users/LocalOwner/runtime-state\n", encoding="utf-8")

    result = classify_tree(root)
    record_paths = {item["path"] for item in result["records"]}
    product_paths = {item["path"] for item in result["product_records"]}

    assert result["valid"], result["errors"]
    assert not (record_paths & set(paths))
    assert not (product_paths & set(paths))


def test_governance_and_receipt_progress_cannot_mutate_frozen_product_identity() -> None:
    root = _minimal_tree()
    controls = {
        ".engineering-bootstrap/admission-payloads/release-stage.json": '{"effect":"execute"}\n',
        ".engineering-bootstrap/processing-order/repair-campaign.json": '{"phase":"repair_frozen"}\n',
        ".engineering-bootstrap/processing-order/release-identity.json": '{"state":"cleared"}\n',
        ".engineering-bootstrap/test-evidence/sections/testing-governance.json": '{"passed":true}\n',
        ".engineering-bootstrap/test-evidence/groups/core-a-f.json": '{"passed":true}\n',
        ".engineering-bootstrap/resource-lifecycle/cleanup-receipts/process.json": '{"status":"exited"}\n',
        "extension/SHA256SUMS.txt": "old  dist/package.vsix\n",
        "registry/.operational-gap-ledger.lock": '{"owner":"one"}\n',
        "registry/completion_status.json": '{"complete":false}\n',
        "registry/operational_gap_ledger.head.json": '{"sequence":1}\n',
    }
    for relative, content in controls.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    frozen = classify_tree(root)
    for relative in controls:
        path = root / relative
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    current = classify_tree(root)
    assert frozen["valid"] and current["valid"]
    assert frozen["product_digest"] == current["product_digest"]
    records = {item["path"]: item for item in current["records"]}
    for relative in (
        ".engineering-bootstrap/admission-payloads/release-stage.json",
        ".engineering-bootstrap/processing-order/repair-campaign.json",
        ".engineering-bootstrap/processing-order/release-identity.json",
        ".engineering-bootstrap/test-evidence/sections/testing-governance.json",
        "extension/SHA256SUMS.txt",
        "registry/.operational-gap-ledger.lock",
        "registry/completion_status.json",
        "registry/operational_gap_ledger.head.json",
    ):
        record = records[relative]
        assert record["classification"] == "control_output"
        assert record["sha256"] is None


def test_full_profile_completion_projection_cannot_fail_a_passing_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _minimal_tree()
    extension = root / "extension/package.json"
    extension.parent.mkdir(parents=True)
    extension.write_text('{"version":"1.2.3"}\n', encoding="utf-8")
    completion = root / "registry/completion_status.json"
    completion.parent.mkdir(parents=True)
    completion.write_text('{"complete":false}\n', encoding="utf-8")
    monkeypatch.setattr(
        "runtime.release_campaign.authoritative_version", lambda _root: "1.2.3"
    )

    _write_release_repair_state(root, "repair")
    clear_release_identity(root, campaign_id="completion-control-output")
    _write_release_repair_state(root, "revision_reconciled")
    apply_release_identity(root)
    sections = claim_release_stage(root, "sections")
    finish_release_stage(
        root, stage="sections", claim_id=sections["claim_id"], passed=True
    )
    _write_release_repair_state(root, "sections_current")
    full_profile = claim_release_stage(root, "full_profile")

    completion.write_text('{"complete":true}\n', encoding="utf-8")
    finished = finish_release_stage(
        root,
        stage="full_profile",
        claim_id=full_profile["claim_id"],
        passed=True,
    )

    assert finished["valid"] is True
    assert finished["state"] == "active"
    assert finished["stages"]["full_profile"]["status"] == "passed"


def test_invalid_active_campaign_with_passed_stages_is_archived_before_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _minimal_tree()
    extension = root / "extension/package.json"
    extension.parent.mkdir(parents=True)
    extension.write_text('{"version":"1.2.3"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "runtime.release_campaign.authoritative_version", lambda _root: "1.2.3"
    )
    _write_release_repair_state(root, "repair")
    clear_release_identity(root, campaign_id="active-before-defect")
    _write_release_repair_state(root, "revision_reconciled")
    apply_release_identity(root)
    sections = claim_release_stage(root, "sections")
    finish_release_stage(
        root, stage="sections", claim_id=sections["claim_id"], passed=True
    )

    (root / "runtime/module.py").write_text("VALUE = 2\n", encoding="utf-8")
    _write_release_repair_state(root, "repair_frozen")
    superseded = supersede_invalid_active_release_campaign(
        root,
        campaign_id="active-after-defect",
        reason="focused pre-package source defect",
    )

    assert superseded["state"] == "cleared"
    assert superseded["apply_count"] == 0
    archive = root / superseded["superseded_archive"]
    retained = __import__("json").loads(archive.read_text(encoding="utf-8"))
    assert retained["campaign_state"]["campaign_id"] == "active-before-defect"
    assert retained["campaign_state"]["stages"]["sections"]["status"] == "passed"


def test_failed_stage_rewinds_only_from_its_exact_repair_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _minimal_tree()
    extension = root / "extension/package.json"
    extension.parent.mkdir(parents=True)
    extension.write_text('{"version":"1.2.3"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "runtime.release_campaign.authoritative_version", lambda _root: "1.2.3"
    )
    _write_release_repair_state(root, "repair")
    clear_release_identity(root, campaign_id="failed-stage")
    _write_release_repair_state(root, "revision_reconciled")
    apply_release_identity(root)
    claim = claim_release_stage(root, "sections")
    finish_release_stage(
        root, stage="sections", claim_id=claim["claim_id"], passed=False
    )

    rewind = rewind_failed_release_campaign_repair(root)

    assert rewind["valid"] is True
    assert rewind["failed_stage"] == "sections"
    assert rewind["prior_phase"] == "revision_reconciled"
    assert rewind["phase"] == "repair_frozen"


def _write_release_repair_state(root: Path, phase: str) -> None:
    campaign = root / ".engineering-bootstrap/processing-order/repair-campaign.json"
    campaign.parent.mkdir(parents=True, exist_ok=True)
    campaign.write_text(
        '{"schema_version":"px.repair-campaign/1.0",'
        f'"campaign_id":"repair-exact","phase":"{phase}",'
        '"intake_open":false,"unresolved":[]}\n',
        encoding="utf-8",
    )


def test_real_classifier_is_stable_across_identity_apply_and_invalid_supersession(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _minimal_tree()
    extension = root / "extension/package.json"
    extension.parent.mkdir(parents=True)
    extension.write_text('{"version":"1.2.3"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "runtime.release_campaign.authoritative_version", lambda _root: "1.2.3"
    )
    _write_release_repair_state(root, "repair")
    clear_release_identity(root, campaign_id="identity-invalid")
    before_apply = classify_tree(root)
    _write_release_repair_state(root, "revision_reconciled")
    applied = apply_release_identity(root)
    after_apply = classify_tree(root)
    assert applied["valid"] is True
    assert applied["apply_count"] == 1
    assert before_apply["product_digest"] == after_apply["product_digest"]
    identity_record = next(
        item
        for item in after_apply["records"]
        if item["path"]
        == ".engineering-bootstrap/processing-order/release-identity.json"
    )
    assert identity_record["classification"] == "control_output"
    assert identity_record["sha256"] is None

    _write_release_repair_state(root, "repair_frozen")
    with pytest.raises(
        ReleaseCampaignBlocked, match="coherent release identity cannot be superseded"
    ):
        supersede_invalid_release_identity(
            root,
            campaign_id="identity-must-not-replace-valid",
            reason="invalid attempt to replace a coherent identity",
        )

    _write_release_repair_state(root, "revision_reconciled")
    (root / "runtime/module.py").write_text("VALUE = 2\n", encoding="utf-8")
    rewind = rewind_invalid_release_identity_reconciliation(root)
    assert rewind["valid"] is True
    assert rewind["phase"] == "repair_frozen"
    superseded = supersede_invalid_release_identity(
        root,
        campaign_id="identity-corrected",
        reason="focused source-drift recovery",
    )
    assert superseded["state"] == "cleared"
    assert superseded["apply_count"] == 0
    archive = root / superseded["superseded_archive"]
    retained = __import__("json").loads(archive.read_text(encoding="utf-8"))
    assert retained["campaign_state"]["campaign_id"] == "identity-invalid"
    assert retained["campaign_state"]["apply_count"] == 1
    _write_release_repair_state(root, "revision_reconciled")
    corrected = apply_release_identity(root)
    assert corrected["valid"] is True
    assert corrected["campaign_id"] == "identity-corrected"
    assert corrected["apply_count"] == 1


def test_current_product_tree_identity_apply_is_a_fixed_point(tmp_path: Path) -> None:
    root = tmp_path / "current-product-source"
    receipt = materialize_release_source(ROOT, root)
    assert receipt["valid"], receipt
    _write_release_repair_state(root, "repair")
    clear_release_identity(root, campaign_id="exact-current-product")
    cleared = classify_tree(root)
    _write_release_repair_state(root, "revision_reconciled")
    applied = apply_release_identity(root)
    active = classify_tree(root)
    assert applied["valid"] is True
    assert applied["apply_count"] == 1
    assert applied["identity"]["source_product_digest"] == cleared["product_digest"]
    assert active["product_digest"] == cleared["product_digest"]
    assert active["harness_digest"] == cleared["harness_digest"]


def test_control_output_prefix_does_not_hide_neighboring_product_source() -> None:
    root = _minimal_tree()
    source = root / ".engineering-bootstrap/test-evidence-contract.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    frozen = classify_tree(root)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    current = classify_tree(root)
    record = next(item for item in current["records"] if item["path"] == source.relative_to(root).as_posix())
    assert record["classification"] == "product_input"
    assert frozen["product_digest"] != current["product_digest"]


def test_retained_wal_transaction_custody_is_control_output() -> None:
    root = _minimal_tree()
    first = classify_tree(root)
    journal = root / ".engineering-bootstrap/wal/cohesion/committed/tx/manifest.json"
    journal.parent.mkdir(parents=True)
    journal.write_text('{"state":"committed"}\n', encoding="utf-8")
    second = classify_tree(root)
    record = next(
        item for item in second["records"] if item["path"] == journal.relative_to(root).as_posix()
    )
    assert second["valid"], second["errors"]
    assert record["classification"] == "control_output"
    assert first["product_digest"] == second["product_digest"]


def test_nested_evidence_is_not_a_product_input() -> None:
    root = _minimal_tree()
    evidence = root / "runtime/evidence/result.json"
    evidence.parent.mkdir()
    evidence.write_text("{}\n", encoding="utf-8")
    first = classify_tree(root)
    record = next(
        item
        for item in first["records"]
        if item["path"] == "runtime/evidence/result.json"
    )
    evidence.write_text('{"changed":true}\n', encoding="utf-8")
    second = classify_tree(root)
    assert first["valid"] and second["valid"]
    assert record["classification"] == "evidence_output"
    assert first["product_digest"] == second["product_digest"]


def test_junit_xml_is_an_admitted_non_executable_evidence_format() -> None:
    root = _minimal_tree()
    report = root / "evidence/release-runs/example/full-tests.junit.xml"
    report.parent.mkdir(parents=True)
    report.write_text(
        '<testsuites tests="1" failures="0" errors="0" skipped="0" />\n',
        encoding="utf-8",
    )
    result = classify_tree(root)
    assert result["valid"], result["errors"]


def test_ndjson_progress_is_an_admitted_non_executable_evidence_format() -> None:
    root = _minimal_tree()
    report = root / "evidence/operational-walk/profile-progress.ndjson"
    report.parent.mkdir(parents=True)
    report.write_text('{"phase":"running"}\n', encoding="utf-8")
    result = classify_tree(root)
    assert result["valid"], result["errors"]


def test_setuptools_egg_info_is_generated_intermediate_not_product() -> None:
    root = _minimal_tree()
    first = classify_tree(root)
    metadata = root / "engineering_loop_bootstrap.egg-info/PKG-INFO"
    metadata.parent.mkdir()
    metadata.write_text("Metadata-Version: 2.4\n", encoding="utf-8")
    second = classify_tree(root)
    record = next(
        item for item in second["records"] if item["path"].endswith("PKG-INFO")
    )
    assert second["valid"], second["errors"]
    assert record["classification"] == "generated_intermediate"
    assert first["product_digest"] == second["product_digest"]


def test_git_metadata_is_excluded_retained_custody_not_product() -> None:
    root = _minimal_tree()
    first = classify_tree(root)
    metadata = root / ".git/objects/example"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("git metadata\n", encoding="utf-8")
    second = classify_tree(root)
    assert second["valid"], second["errors"]
    assert not any(item["path"].startswith(".git/") for item in second["records"])
    assert first["product_digest"] == second["product_digest"]


def test_px_native_skills_are_product_and_nested_dependencies_are_pruned() -> None:
    root = _minimal_tree()
    native = root / ".px/skills/example/SKILL.md"
    native.parent.mkdir(parents=True)
    native.write_text("# Example\n", encoding="utf-8")
    dependency = root / "extension/node_modules/example/dist/index.js"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("generated dependency\n", encoding="utf-8")
    result = classify_tree(root)
    assert result["valid"], result["errors"]
    assert any(
        item["path"] == ".px/skills/example/SKILL.md"
        and item["classification"] == "product_input"
        for item in result["records"]
    )
    assert not any(item["path"].startswith("extension/node_modules/") for item in result["records"])


def test_materialized_release_source_is_bounded_and_complete() -> None:
    with tempfile.TemporaryDirectory() as directory:
        destination = Path(directory) / "source"
        receipt = materialize_release_source(
            ROOT,
            destination,
            extra_paths=("evidence/externalized-payload-index.json",),
        )

        assert receipt["valid"]
        assert receipt["copied_bytes"] < 256 * 1024 * 1024
        assert receipt["declared_evidence_file_count"] == len(
            DECLARED_PACKAGED_EVIDENCE
        )
        for relative in DECLARED_PACKAGED_EVIDENCE:
            assert (destination / relative).read_bytes() == (
                ROOT / relative
            ).read_bytes()
        assert (destination / "pyproject.toml").read_bytes() == (
            ROOT / "pyproject.toml"
        ).read_bytes()
        assert (destination / "runtime/release_artifacts.py").is_file()
        assert (destination / "evidence/externalized-payload-index.json").is_file()
        assert not (destination / "registry/operational_gap_ledger.jsonl").exists()
        assert not (
            destination / "registry/operational_gap_ledger.snapshot.json"
        ).exists()
        assert not (destination / "registry/operational_gap_ledger.head.json").exists()


def test_materialized_release_source_rejects_existing_destination() -> None:
    with tempfile.TemporaryDirectory() as directory:
        destination = Path(directory) / "source"
        destination.mkdir()
        with pytest.raises(FileExistsError, match="already exists"):
            materialize_release_source(ROOT, destination)


def test_materialized_release_source_rejects_path_traversal() -> None:
    with tempfile.TemporaryDirectory() as directory:
        with pytest.raises(ValueError, match="unsafe release fixture path"):
            materialize_release_source(
                ROOT,
                Path(directory) / "source",
                extra_paths=("../outside",),
            )
