from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts.run_release_candidate import (
    AutomationBlocked,
    Config,
    RELEASE_STAGE_PHASES,
    SubprocessOwners,
    STEP_ORDER,
    execute_next,
    next_pending_step,
    plan,
    readiness,
    validate_installed_summary,
)


class FakeOwners:
    def __init__(self, *, fail: str | None = None):
        self.fail = fail
        self.runs: list[str] = []
        self.verified: list[str] = []

    def run(self, step: str, commands: tuple[tuple[str, ...], ...]):
        self.runs.append(step)
        return {"valid": step != self.fail, "commands": len(commands)}

    def verify(self, step: str) -> None:
        self.verified.append(step)


def config(tmp_path: Path) -> Config:
    artifact = tmp_path / "candidate.vsix"
    artifact.write_bytes(b"exact")
    stat = artifact.stat()
    return Config(
        root=tmp_path,
        candidate_id="PX-20260905-001",
        candidate_date="20260905",
        predecessor_campaign_id="PX-OLD",
        repair_campaign_id="PX-REPAIR",
        evidence_prefix="candidate",
        artifact=artifact,
        artifact_sha256=hashlib.sha256(b"exact").hexdigest(),
        artifact_size=stat.st_size,
        artifact_mtime_ns=stat.st_mtime_ns,
        automation_state=tmp_path / "state.json",
        log_root=tmp_path / "logs",
        installed_summary=tmp_path / "installed.json",
        installed_exhaustive_receipt=tmp_path / "walk-receipt.json",
        cohesion_dag=tmp_path / "dag.json",
        identity_path_manifest=tmp_path / "identity-manifest.json",
        timeouts_seconds={step: 60 for step in STEP_ORDER},
        fresh_paths=(tmp_path / "fresh",),
        owners={step: (("owner", step),) for step in STEP_ORDER},
    )


def test_plan_is_read_only_and_canonical(tmp_path: Path) -> None:
    value = config(tmp_path)
    result = plan(value)
    assert [item["step"] for item in result["steps"]] == list(STEP_ORDER)
    assert result["default_mode"] == "plan-only"
    assert not value.automation_state.exists()


def test_initial_readiness_allows_one_unused_cleared_predecessor(
    tmp_path: Path,
) -> None:
    value = config(tmp_path)
    control = tmp_path / ".engineering-bootstrap/processing-order"
    control.mkdir(parents=True)
    (control / "repair-campaign.json").write_text(
        json.dumps(
            {
                "campaign_id": value.repair_campaign_id,
                "phase": "repair_frozen",
                "intake_open": False,
                "unresolved": [],
            }
        ),
        encoding="utf-8",
    )
    (control / "release-identity.json").write_text(
        json.dumps(
            {
                "campaign_id": value.predecessor_campaign_id,
                "state": "cleared",
                "apply_count": 0,
                "identity": None,
                "active_claim": None,
            }
        ),
        encoding="utf-8",
    )
    assert readiness(value)["valid"] is True


def test_initial_readiness_allows_one_unused_invalid_identity_predecessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = config(tmp_path)
    control = tmp_path / ".engineering-bootstrap/processing-order"
    control.mkdir(parents=True)
    (control / "repair-campaign.json").write_text(
        json.dumps(
            {
                "campaign_id": value.repair_campaign_id,
                "phase": "revision_reconciled",
                "intake_open": False,
                "unresolved": [],
            }
        ),
        encoding="utf-8",
    )
    (control / "release-identity.json").write_text(
        json.dumps(
            {
                "campaign_id": value.predecessor_campaign_id,
                "state": "active",
                "apply_count": 1,
                "identity": {"release_identity_sha256": "a" * 64},
                "active_claim": None,
                "stages": {
                    name: {"status": "pending", "claim_id": None}
                    for name in (
                        "sections",
                        "full_profile",
                        "validate",
                        "package",
                        "install",
                        "installed_operational",
                        "certify",
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runtime.release_campaign.release_campaign_status",
        lambda root, verify_source=False: {
            "valid": not verify_source,
            "errors": ["drift"] if verify_source else [],
        },
    )
    assert readiness(value)["valid"] is True


def test_initial_readiness_allows_only_source_invalid_active_retained_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = config(tmp_path)
    control = tmp_path / ".engineering-bootstrap/processing-order"
    control.mkdir(parents=True)
    (control / "repair-campaign.json").write_text(
        json.dumps({
            "campaign_id": value.repair_campaign_id,
            "phase": "repair_frozen",
            "intake_open": False,
            "unresolved": [],
        }),
        encoding="utf-8",
    )
    stages = {
        name: {"status": "passed" if index < 6 else "pending", "claim_id": None}
        for index, name in enumerate(RELEASE_STAGE_PHASES)
    }
    (control / "release-identity.json").write_text(
        json.dumps({
            "campaign_id": value.predecessor_campaign_id,
            "state": "active",
            "apply_count": 1,
            "identity": {"release_identity_sha256": "a" * 64},
            "active_claim": None,
            "stages": stages,
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "runtime.release_campaign.release_campaign_status",
        lambda root, verify_source=False: {
            "valid": not verify_source,
            "errors": ["source drift"] if verify_source else [],
        },
    )
    assert readiness(value)["valid"] is True

    repair = json.loads((control / "repair-campaign.json").read_text(encoding="utf-8"))
    repair["phase"] = "installed_operational"
    (control / "repair-campaign.json").write_text(json.dumps(repair), encoding="utf-8")
    assert readiness(value)["valid"] is False

    repair["phase"] = "repair_frozen"
    (control / "repair-campaign.json").write_text(json.dumps(repair), encoding="utf-8")
    monkeypatch.setattr(
        "runtime.release_campaign.release_campaign_status",
        lambda root, verify_source=False: {"valid": True, "errors": []},
    )
    assert readiness(value)["valid"] is False

    monkeypatch.setattr(
        "runtime.release_campaign.release_campaign_status",
        lambda root, verify_source=False: {
            "valid": False,
            "errors": ["structural"] if not verify_source else ["source drift"],
        },
    )
    assert readiness(value)["valid"] is False

    monkeypatch.setattr(
        "runtime.release_campaign.release_campaign_status",
        lambda root, verify_source=False: {
            "valid": not verify_source,
            "errors": ["source drift"] if verify_source else [],
        },
    )
    release_path = control / "release-identity.json"
    malformed = json.loads(release_path.read_text(encoding="utf-8"))
    malformed["active_claim"] = {"stage": "certify"}
    release_path.write_text(json.dumps(malformed), encoding="utf-8")
    assert readiness(value)["valid"] is False

    malformed["active_claim"] = None
    malformed["stages"]["validate"]["status"] = "pending"
    malformed["stages"]["package"]["status"] = "passed"
    release_path.write_text(json.dumps(malformed), encoding="utf-8")
    assert readiness(value)["valid"] is False


def test_initial_readiness_allows_failed_stage_at_exact_repair_phase(
    tmp_path: Path,
) -> None:
    value = config(tmp_path)
    control = tmp_path / ".engineering-bootstrap/processing-order"
    control.mkdir(parents=True)
    (control / "repair-campaign.json").write_text(
        json.dumps(
            {
                "campaign_id": value.repair_campaign_id,
                "phase": "revision_reconciled",
                "intake_open": False,
                "unresolved": [],
            }
        ),
        encoding="utf-8",
    )
    (control / "release-identity.json").write_text(
        json.dumps(
            {
                "campaign_id": value.predecessor_campaign_id,
                "state": "failed",
                "apply_count": 1,
                "identity": {"release_identity_sha256": "a" * 64},
                "active_claim": None,
                "stages": {
                    name: {
                        "status": "failed" if name == "sections" else "pending",
                        "claim_id": "claim" if name == "sections" else None,
                    }
                    for name in RELEASE_STAGE_PHASES
                },
            }
        ),
        encoding="utf-8",
    )
    assert readiness(value)["valid"] is True


def test_identity_manifest_is_written_before_owner_and_contains_only_dirty_sets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = config(tmp_path)
    monkeypatch.setattr(
        "runtime.release_identity._release_dirty_state",
        lambda root: {
            "blocking_paths": ["source.py"],
            "mutable_control_paths": ["evidence/base.json"],
            "classifier_errors": [],
        },
    )
    monkeypatch.setattr(SubprocessOwners, "verify", lambda self, step: None)

    class Process:
        def wait(self, *, timeout: float) -> int:
            assert timeout > 0
            return 0

    class Manager:
        def spawn_owned_process(self, argv: list[str], **kwargs: object):
            assert (value.log_root / "candidate-identity.log").is_file()
            manifest = json.loads(
                value.identity_path_manifest.read_text(encoding="utf-8")
            )
            assert manifest["paths"] == ["source.py"]
            assert manifest["mutable_paths"] == ["evidence/base.json"]
            return SimpleNamespace(resource_id="process-one", pid=123), Process()

        def complete_process(self, resource_id: str):
            assert resource_id == "process-one"
            return SimpleNamespace(
                status="reclaimed", run_state="completed", cleanup_result="exit_0"
            )

    result = SubprocessOwners(value, Manager()).run(
        "identity", (("owner", "identity"),)
    )
    assert result["valid"] is True


def test_final100_identity_outputs_are_outside_the_git_dirty_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    driver = Config.load(
        root / ".engineering-bootstrap/processing-order/final100-release-automation.json"
    )
    from scripts.run_release_stage_owner import Config as StageConfig

    stage = StageConfig.load(
        root / ".engineering-bootstrap/processing-order/final100-stage-owner.json"
    )
    assert driver.identity_path_manifest == stage.path_manifest
    candidates = [
        driver.identity_path_manifest,
        driver.log_root / "final100-identity.log",
        stage.evidence_dir / f"{driver.candidate_id}-identity.json",
        root / ".engineering-bootstrap/resource-lifecycle/ledger.json",
    ]
    assert all(
        subprocess.run(
            ["git", "check-ignore", "-q", "--", str(path)],
            cwd=root,
            check=False,
        ).returncode
        == 0
        for path in candidates
    )


def test_owner_timeout_terminates_exact_registered_process_tree(
    tmp_path: Path,
) -> None:
    value = config(tmp_path)

    class Process:
        def wait(self, *, timeout: float) -> int:
            raise subprocess.TimeoutExpired(["owner"], timeout)

    class Manager:
        terminated: list[str] = []

        def spawn_owned_process(self, argv: list[str], **kwargs: object):
            return SimpleNamespace(resource_id="process-timeout", pid=456), Process()

        def terminate_owned_process(self, resource_id: str):
            self.terminated.append(resource_id)
            return SimpleNamespace(
                cleanup_id="cleanup-timeout",
                resources_reclaimed=1,
                resources_failed=0,
                errors=(),
            )

    manager = Manager()
    with pytest.raises(AutomationBlocked, match="bounded deadline"):
        SubprocessOwners(value, manager).run(
            "archive_clear", (("owner", "archive_clear"),)
        )
    assert manager.terminated == ["process-timeout"]


def test_each_invocation_runs_exactly_one_next_step(tmp_path: Path) -> None:
    value = config(tmp_path)
    owners = FakeOwners()
    first = execute_next(
        value, owners, admission_event_id="gap-event:33728", gap_id="PX-OS-1067"
    )
    assert first["executed_step"] == "archive_clear"
    assert first["next_step"] == "reconcile"
    second = execute_next(
        value, owners, admission_event_id="gap-event:33729", gap_id="PX-OS-1067"
    )
    assert second["executed_step"] == "reconcile"
    assert owners.runs == ["archive_clear", "reconcile"]
    state = json.loads(value.automation_state.read_text(encoding="utf-8"))
    assert state["steps"]["archive_clear"]["admission_event_id"] == "gap-event:33728"
    assert state["steps"]["reconcile"]["admission_event_id"] == "gap-event:33729"


def test_failed_step_is_journaled_once_and_never_retried(tmp_path: Path) -> None:
    value = config(tmp_path)
    owners = FakeOwners(fail="archive_clear")
    with pytest.raises(AutomationBlocked, match="cannot be retried"):
        execute_next(
            value, owners, admission_event_id="gap-event:33728", gap_id="PX-OS-1067"
        )
    with pytest.raises(AutomationBlocked, match="no retry"):
        execute_next(
            value, owners, admission_event_id="gap-event:33729", gap_id="PX-OS-1067"
        )
    assert owners.runs == ["archive_clear"]


def test_running_state_fails_closed_without_owner_launch(tmp_path: Path) -> None:
    value = config(tmp_path)
    value.automation_state.write_text(json.dumps({
        "schema_version": "px.release-candidate-automation-state/1.0",
        "candidate_id": value.candidate_id,
        "steps": {"archive_clear": {"status": "running"}},
    }), encoding="utf-8")
    owners = FakeOwners()
    with pytest.raises(AutomationBlocked, match="no retry"):
        next_pending_step(value, owners)
    assert owners.runs == []


def test_all_twelve_invocations_advance_without_replaying(tmp_path: Path) -> None:
    value = config(tmp_path)
    owners = FakeOwners()
    for index, expected in enumerate(STEP_ORDER, 1):
        result = execute_next(
            value, owners, admission_event_id=f"gap-event:{index}",
            gap_id="PX-OS-1067",
        )
        assert result["executed_step"] == expected
    assert owners.runs == list(STEP_ORDER)
    assert owners.verified.count("archive_clear") == (2 * len(STEP_ORDER)) - 1
    assert next_pending_step(value, owners) is None


def test_config_requires_four_card_reconcile_checks_then_applies(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.vsix"
    artifact.write_bytes(b"exact")
    stat = artifact.stat()
    owners = {
        step: {"commands": [["owner", step]]}
        for step in STEP_ORDER
    }
    owners["card_reconcile"] = {"commands": [
        ["python", "-B", "scripts/reconcile_unverified_operational_controls.py", "--root", ".", "--check", "--walk-receipt", "walk-receipt.json", "--reconcile-cards"],
        ["python", "-B", "scripts/reconcile_cohesion_cards.py", "--root", ".", "--target", "closed", "--installed-proof", "installed.json", "--automation-state", "state.json"],
        ["python", "-B", "scripts/reconcile_unverified_operational_controls.py", "--root", ".", "--walk-receipt", "walk-receipt.json", "--reconcile-cards"],
        ["python", "-B", "scripts/reconcile_cohesion_cards.py", "--root", ".", "--target", "closed", "--installed-proof", "installed.json", "--automation-state", "state.json", "--apply"],
    ]}
    raw = {
        "schema_version": "px.release-candidate-automation/1.0",
        "root": str(tmp_path), "candidate_id": "PX-20260905-001",
        "candidate_date": "20260905", "predecessor_campaign_id": "PX-OLD",
        "repair_campaign_id": "PX-REPAIR", "evidence_prefix": "candidate",
        "artifact": "candidate.vsix",
        "artifact_sha256": "2f2d5c9fa210a7ea7c1d4a39a5f3c54d8cb12c7d70c3e225f73f5b2634a7de31",
        "artifact_size": stat.st_size, "artifact_mtime_ns": stat.st_mtime_ns,
        "automation_state": "state.json", "log_root": "logs",
        "installed_summary": "installed.json",
        "installed_exhaustive_receipt": "walk-receipt.json",
        "cohesion_dag": "dag.json",
        "identity_manifest": {
            "path": "identity-manifest.json",
        },
        "timeouts_seconds": {step: 60 for step in STEP_ORDER},
        "fresh_paths": ["fresh"], "owners": owners,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert len(Config.load(path).owners["card_reconcile"]) == 4

    for command_index in range(4):
        invalid = json.loads(json.dumps(raw))
        invalid["owners"]["card_reconcile"]["commands"][command_index].append("--extra")
        path.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(AutomationBlocked, match="exact installed-proof sequence"):
            Config.load(path)

    path.write_text(json.dumps(raw), encoding="utf-8")
    owners["card_reconcile"]["commands"][-1].remove("--apply")
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(AutomationBlocked, match="exact installed-proof sequence"):
        Config.load(path)


def test_installed_summary_rejects_identity_and_receipt_cross_binding_drift(tmp_path: Path) -> None:
    value = config(tmp_path)
    identity_sha = "1" * 64
    product_sha = "2" * 64
    harness_sha = "3" * 64
    package_claim = f"release-stage:{value.candidate_id}:package:one"
    install_claim = f"release-stage:{value.candidate_id}:install:one"
    operational_claim = f"release-stage:{value.candidate_id}:installed_operational:one"
    kernel = value.root / ".engineering-bootstrap/processing-order"
    kernel.mkdir(parents=True)
    (kernel / "release-identity.json").write_text(json.dumps({
        "campaign_id": value.candidate_id,
        "identity": {
            "release_identity_sha256": identity_sha,
            "source_product_digest": product_sha,
            "source_harness_digest": harness_sha,
        },
        "stages": {
            "package": {"claim_id": package_claim},
            "install": {"claim_id": install_claim},
            "installed_operational": {"claim_id": operational_claim},
        },
    }), encoding="utf-8")

    def write_json(name: str, payload: object) -> Path:
        path = value.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def evidence(path: Path) -> dict[str, str]:
        return {
            "path": path.relative_to(value.root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    artifact_binding = {
        "path": "candidate.vsix", "sha256": value.artifact_sha256,
        "size": value.artifact_size,
    }
    common = {
        "campaign_id": value.candidate_id,
        "release_identity_sha256": identity_sha,
        "source_product_digest": product_sha,
        "source_harness_digest": harness_sha,
        "artifact": artifact_binding,
    }
    package_payload = {
        **common,
        "schema_version": "px.release-stage-evidence/1.0",
        "claim_id": package_claim,
        "stage": "package",
        "status": "passed",
        "attempt_count": 1,
        "artifact_mtime_ns": value.artifact_mtime_ns,
        "entry_count": 2,
        "unique_entry_count": 2,
        "crc_clean": True,
        "unsafe_path_count": 0,
        "encrypted_count": 0,
        "symlink_count": 0,
        "artifact_unchanged": True,
        "artifact_rebuilt": False,
        "artifact_touched": False,
        "resource_count": 0,
        "active_processes": 0,
        "cleanup_failures": 0,
        "valid": True,
    }
    install_payload = {
        **common,
        "schema_version": "px.install-audit-denominator/1.0",
        "claim_id": install_claim,
        "install_claim_id": install_claim,
        "listed_owned_versions": ["mountain-nomad-bc.pacify-x-vscode@0.6.85"],
        "exact_version_count": 1,
        "installable_entry_count": 2,
        "installed_file_count": 2,
        "verified_byte_identical_entries": 1,
        "normalized_package_json_entries": 1,
        "missing": [],
        "extra": [],
        "mismatches": [],
        "crc_failures": [],
        "installed_symlinks_before": [],
        "installed_symlinks_after": [],
        "tree_digest_before": "4" * 64,
        "tree_digest_after": "4" * 64,
        "installed_tree_unchanged": True,
        "machine_mutated": False,
        "install_command_executed": False,
        "release_stage": "passed",
        "processing_phase": "installed",
        "resource_count": 0,
        "active_processes": 0,
        "cleanup_failures": 0,
        "audit_valid": True,
        "valid": True,
    }
    package = write_json("package.json", package_payload)
    install = write_json("install.json", install_payload)
    smoke_log = write_json("smoke-log.json", {"ok": True})
    smoke_receipt = write_json("smoke-receipt.json", {"ok": True})
    lifecycle = write_json("lifecycle.json", {"closed": True})
    walk_receipt = write_json("walk-receipt.json", {
        "hostErrors": [], "profileFailures": [],
    })
    report = write_json("walk-report.json", {
        "status_truth": {"terminal_state": "completed", "operationally_complete": True,
                         "summary": {"issue_count": 0, "blocking_issue_count": 0}},
        "child_lifecycle": {"operational_status": {"scope_complete": True},
                            "installed_artifact": {"unchanged_after_install": True}},
        "owner_lifecycle": {"process_tree_closed_verified": True},
        "cleanup": {"reclaimed": True},
    })
    def smoke_member(name: str) -> dict[str, object]:
        return {
            "member": name, "exit_code": 0, "log": evidence(smoke_log),
            "receipt": evidence(smoke_receipt),
            "process_lifecycle_receipt": evidence(lifecycle),
            "artifact_unchanged": True, "process_tree_closed_verified": True,
        }
    summary = {
        "schema_version": "px.installed-operational-run-summary/1.1",
        "campaign_id": value.candidate_id, "claim_id": operational_claim,
        "finished_utc": "2026-09-06T00:00:00Z",
        "release_identity_sha256": identity_sha,
        "source_product_digest": product_sha, "source_harness_digest": harness_sha,
        "artifact": artifact_binding, "package_receipt": evidence(package),
        "install_receipt": evidence(install), "all_passed": True, "retries": 0,
        "cross_platform_smokes_parallel": True, "windows_hosts_serialized": True,
        "members": [smoke_member("windows-exact-vsix-smoke"),
                    smoke_member("ubuntu-exact-vsix-smoke"), {
            "member": "exhaustive-installed-exact-vsix-host-walk", "exit_code": 0,
            "log": evidence(smoke_log), "receipt": evidence(walk_receipt),
            "report": evidence(report), "terminal_state": "completed",
            "scope_complete": True, "operationally_complete": True,
            "issue_count": 0, "blocking_issue_count": 0, "host_error_count": 0,
            "profile_failure_count": 0, "process_tree_closed_verified": True,
            "workspace_reclaimed": True, "artifact_unchanged": True,
        }],
    }
    value.installed_summary.write_text(json.dumps(summary), encoding="utf-8")
    assert validate_installed_summary(value)["all_passed"] is True
    package_payload["status"] = "failed"
    package.write_text(json.dumps(package_payload), encoding="utf-8")
    summary["package_receipt"] = evidence(package)
    value.installed_summary.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(AutomationBlocked, match="package receipt contradicts"):
        validate_installed_summary(value)
    package_payload["status"] = "passed"
    package.write_text(json.dumps(package_payload), encoding="utf-8")
    summary["package_receipt"] = evidence(package)
    install_payload["audit_valid"] = False
    install.write_text(json.dumps(install_payload), encoding="utf-8")
    summary["install_receipt"] = evidence(install)
    value.installed_summary.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(AutomationBlocked, match="install receipt contradicts"):
        validate_installed_summary(value)
    install_payload["audit_valid"] = True
    install.write_text(json.dumps(install_payload), encoding="utf-8")
    summary["install_receipt"] = evidence(install)
    summary["source_product_digest"] = "4" * 64
    value.installed_summary.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(AutomationBlocked, match="source_product_digest"):
        validate_installed_summary(value)
    summary["source_product_digest"] = product_sha
    package_payload["source_harness_digest"] = "4" * 64
    package.write_text(json.dumps(package_payload), encoding="utf-8")
    summary["package_receipt"] = evidence(package)
    value.installed_summary.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(AutomationBlocked, match="package receipt source_harness_digest"):
        validate_installed_summary(value)
