from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest
import scripts.reconcile_cohesion_cards as reconciliation

from scripts.reconcile_cohesion_cards import (
    ALL_CARD_IDS,
    CARD_DIRECTORY,
    DEFAULT_EVIDENCE,
    SOURCE_CARD_IDS,
    ReconciliationError,
    reconcile,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OBSERVED_HEAD = "a" * 40
AUTOMATION_STATE = Path("evidence/release/final100-automation-state.json")


def _reconcile(root: Path, **kwargs: object) -> dict[str, object]:
    return reconcile(root, observed_head=OBSERVED_HEAD, **kwargs)


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _manifest(directory: Path) -> None:
    names = ["dag.json", *sorted(f"{card_id}.json" for card_id in ALL_CARD_IDS), "README.md"]
    (directory / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256((directory / name).read_bytes()).hexdigest()}  {name}\n"
            for name in names
        ),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    directory = root / CARD_DIRECTORY
    shutil.copytree(REPOSITORY_ROOT / CARD_DIRECTORY, directory)
    for card_id in SOURCE_CARD_IDS:
        path = directory / f"{card_id}.json"
        card = json.loads(path.read_text(encoding="utf-8"))
        card["status"] = "planned"
        card["completion_evidence"] = []
        card.pop("status_history", None)
        card.pop("closure_reconciliation", None)
        _json(path, card)
    dag_path = directory / "dag.json"
    dag = json.loads(dag_path.read_text(encoding="utf-8"))
    dag["progress"] = {
        "closed_audit_cards": 6,
        "closed_source_or_proof_cards": 0,
        "remaining_source_or_proof_cards": 37,
        "active_card": "PX-ASSURE-001",
        "last_closed_card": None,
    }
    _json(dag_path, dag)
    (directory / "README.md").write_text("initial projection\n", encoding="utf-8")
    _manifest(directory)
    state_path = root / ".engineering-bootstrap/project-management/state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPOSITORY_ROOT / ".engineering-bootstrap/project-management/state.json",
        state_path,
    )

    for name in ("finding-dispositions.json", "current-owners-and-gaps.json", "live-state.json"):
        source_path = (
            REPOSITORY_ROOT
            / "evidence/commencement-audit-20260905T002921Z"
            / name
        )
        target = root / source_path.relative_to(REPOSITORY_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
    for card_id in SOURCE_CARD_IDS:
        card = json.loads((directory / f"{card_id}.json").read_text(encoding="utf-8"))
        declared = root / card["files"][0]
        declared.parent.mkdir(parents=True, exist_ok=True)
        if not declared.exists():
            declared.write_text("{}\n" if declared.suffix == ".json" else "fixture\n")

    def retained(path: str, content: bytes) -> tuple[str, str, int]:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return path, hashlib.sha256(content).hexdigest(), len(content)

    product_digest = "b" * 64
    harness_digest = "c" * 64
    benchmark_path = "evidence/commencement-repair/ledger-benchmark.json"
    _json(
        root / benchmark_path,
        {
            "schema_version": "px.operational-gap-ledger-benchmark/1.0",
            "valid": True,
            "custody_guarantees_changed": False,
            "budget_results": {"append": True, "read": True},
        },
    )
    freeze = {
        "schema_version": "px.repair-freeze/1.0",
        "campaign_id": "pacify-x-cohesion-closure-repair-20260905",
        "phase": "repair_frozen",
        "intake_open": False,
        "unresolved": [],
        "certification_claim": False,
        "source_classification": {
            "valid": True,
            "product_digest": product_digest,
            "harness_digest": harness_digest,
        },
        "resource_state": {
            "resource_count": 0,
            "active_processes": 0,
            "reclaimable_paths": 0,
            "cleanup_failures": 0,
        },
        "ledger_benchmark": benchmark_path,
    }
    final99 = "pacify-x-certification-20260905-final99-single"
    kernel = {
        "schema_version": "px.release-identity-kernel/2.0",
        "campaign_id": final99,
        "repair_campaign_id": "pacify-x-cohesion-closure-repair11-20260905",
        "source_product_digest": "d" * 64,
        "source_harness_digest": harness_digest,
    }
    identity_sha = hashlib.sha256(
        json.dumps(kernel, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _json(
        root / ".engineering-bootstrap/processing-order/release-identity.json",
        {
            "schema_version": "px.release-campaign/1.0",
            "campaign_id": final99,
            "repair_campaign_id": kernel["repair_campaign_id"],
            "state": "failed",
            "apply_count": 1,
            "active_claim": None,
            "identity": {**kernel, "release_identity_sha256": identity_sha},
            "stages": {
                "installed_operational": {"status": "failed", "claim_id": "failed"},
                "certify": {"status": "pending", "claim_id": None},
            },
        },
    )
    full_log, full_sha, _ = retained(".tmp/final99-full.log", b"full")
    full = {
        "schema_version": "px.full-profile-receipt/1.0",
        "campaign_id": final99,
        "release_identity_sha256": identity_sha,
        "owner_invocations": 1,
        "required_group_count": 10,
        "passed_group_count": 10,
        "failed_groups": [],
        "timed_out": False,
        "process_tree_terminated": True,
        "group_refresh_workspace_reclaimed": True,
        "cross_group_workspace_reclaimed": True,
        "resource_count": 0,
        "active_processes": 0,
        "cleanup_failures": 0,
        "full_log": full_log,
        "full_log_sha256": full_sha,
        "stage_status": "passed",
        "valid": True,
    }
    validation_log, validation_sha, _ = retained(".tmp/final99-validation.log", b"validation")
    validation = {
        "schema_version": "px.validation-receipt/1.0",
        "campaign_id": final99,
        "release_identity_sha256": identity_sha,
        "owner_invocations": 1,
        "errors": [],
        "certification_claim": False,
        "resource_count": 0,
        "active_processes": 0,
        "cleanup_failures": 0,
        "validation_log": validation_log,
        "validation_log_sha256": validation_sha,
        "stage_status": "passed",
        "valid": True,
    }
    repair_tests = []
    for index in range(3):
        path, sha, size = retained(f".tmp/repair12-{index}.log", f"repair-{index}".encode())
        repair_tests.append(
            {"reference": path, "artifact_sha256": sha, "artifact_size": size}
        )
    installed = []
    for profile in ("studio-lifecycle", "coordination-memory", "native-dialog-boundary"):
        receipt, receipt_sha, _ = retained(f"evidence/{profile}-receipt", b"receipt")
        report, report_sha, _ = retained(f"evidence/{profile}-report", b"report")
        installed.append(
            {
                "profile": profile,
                "receipt": receipt,
                "receipt_sha256": receipt_sha,
                "report": report,
                "report_sha256": report_sha,
                "terminal_state": "completed",
                "issues": 0,
                "host_errors": 0,
                "cleanup_reclaimed": True,
            }
        )
    artifact_path, artifact_sha, artifact_size = retained(
        "extension/dist/pacify-x-vscode-0.6.85.vsix", b"repair12-vsix"
    )
    repair = {
        "schema_version": "px.focused-repair-evidence/1.0",
        "campaign_id": "pacify-x-cohesion-closure-repair12-20260905",
        "predecessor_release_campaign_id": final99,
        "observed_utc": "2026-09-06T00:26:20Z",
        "status": "focused_green",
        "final99_replayed": False,
        "tests": repair_tests,
        "installed_focused_proofs": installed,
        "immutable_artifact": {
            "reference": artifact_path,
            "artifact_sha256": artifact_sha,
            "artifact_size": artifact_size,
            "unchanged": True,
        },
        "certification_claim": False,
    }
    for relative, payload in zip(
        DEFAULT_EVIDENCE, (freeze, full, validation, repair), strict=True
    ):
        _json(root / relative, payload)
    return root


def _installed_proof(root: Path) -> Path:
    relative = Path("evidence/release/final100-installed-operational-pass.json")
    def artifact(path: str, content: bytes) -> dict[str, object]:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }

    product = artifact(
        "extension/dist/pacify-x-vscode-0.6.85.vsix", b"repair12-vsix"
    )
    campaign_id = "pacify-x-certification-20260906-final100-single"
    package_claim = f"release-stage:{campaign_id}:package:fixture"
    install_claim = f"release-stage:{campaign_id}:install:fixture"
    installed_claim = f"release-stage:{campaign_id}:installed_operational:fixture"
    source_product_digest = "e" * 64
    source_harness_digest = "f" * 64
    kernel = {
        "schema_version": "px.release-identity-kernel/2.0",
        "campaign_id": campaign_id,
        "repair_campaign_id": "pacify-x-cohesion-closure-repair12-20260905",
        "extension_version": "0.6.85",
        "source_product_digest": source_product_digest,
        "source_harness_digest": source_harness_digest,
    }
    identity_sha = hashlib.sha256(
        json.dumps(kernel, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    package_log = artifact(".tmp/final100-package.log", b"package-log")
    package_path = "evidence/release/final100-package.json"
    _json(
        root / package_path,
        {
            "schema_version": "px.release-stage-evidence/1.0",
            "campaign_id": campaign_id,
            "release_identity_sha256": identity_sha,
            "source_product_digest": source_product_digest,
            "source_harness_digest": source_harness_digest,
            "stage": "package",
            "status": "passed",
            "claim_id": package_claim,
            "attempt_count": 1,
            "artifact": product,
            "artifact_unchanged": True,
            "artifact_rebuilt": False,
            "artifact_touched": False,
            "audit_log": package_log["path"],
            "audit_log_sha256": package_log["sha256"],
            "resource_count": 0,
            "active_processes": 0,
            "cleanup_failures": 0,
            "valid": True,
        },
    )
    install_log = artifact(".tmp/final100-install.log", b"install-log")
    install_path = "evidence/release/final100-install.json"
    _json(
        root / install_path,
        {
            "schema_version": "px.install-audit-denominator/1.0",
            "campaign_id": campaign_id,
            "release_identity_sha256": identity_sha,
            "source_product_digest": source_product_digest,
            "source_harness_digest": source_harness_digest,
            "audit_valid": True,
            "install_claim_id": install_claim,
            "artifact": product,
            "tree_digest_before": "1" * 64,
            "tree_digest_after": "1" * 64,
            "installed_tree_unchanged": True,
            "audit_log": install_log["path"],
            "audit_log_sha256": install_log["sha256"],
            "release_stage": "passed",
            "processing_phase": "installed",
            "resource_count": 0,
            "active_processes": 0,
            "cleanup_failures": 0,
            "valid": True,
        },
    )
    package_evidence = artifact(package_path, (root / package_path).read_bytes())
    install_evidence = artifact(install_path, (root / install_path).read_bytes())
    members = []
    for stem, name in (
        ("windows", "windows-exact-vsix-smoke"),
        ("ubuntu", "ubuntu-exact-vsix-smoke"),
    ):
        members.append(
            {
                "member": name,
                "exit_code": 0,
                "log": artifact(f".tmp/{stem}.log", f"{stem}-log".encode()),
                "receipt": artifact(
                    f"evidence/{stem}-receipt.json", f"{stem}-receipt".encode()
                ),
                "process_lifecycle_receipt": artifact(
                    f"evidence/{stem}-process.json", f"{stem}-process".encode()
                ),
                "artifact_unchanged": True,
                "process_tree_closed_verified": True,
            }
        )
    members.append(
        {
            "member": "exhaustive-installed-exact-vsix-host-walk",
            "exit_code": 0,
            "log": artifact(".tmp/exhaustive.log", b"exhaustive-log"),
            "receipt": artifact("evidence/exhaustive-receipt.json", b"exhaustive-receipt"),
            "report": artifact("evidence/exhaustive-report.json", b"exhaustive-report"),
            "terminal_state": "completed",
            "operationally_complete": True,
            "scope_complete": True,
            "issue_count": 0,
            "blocking_issue_count": 0,
            "host_error_count": 0,
            "profile_failure_count": 0,
            "process_tree_closed_verified": True,
            "workspace_reclaimed": True,
            "artifact_unchanged": True,
        }
    )
    _json(
        root / relative,
        {
            "schema_version": "px.installed-operational-run-summary/1.1",
            "campaign_id": campaign_id,
            "claim_id": installed_claim,
            "release_identity_sha256": identity_sha,
            "source_product_digest": source_product_digest,
            "source_harness_digest": source_harness_digest,
            "finished_utc": "2026-09-06T02:00:00Z",
            "artifact": product,
            "package_receipt": package_evidence,
            "install_receipt": install_evidence,
            "retries": 0,
            "all_passed": True,
            "cross_platform_smokes_parallel": True,
            "windows_hosts_serialized": True,
            "members": members,
        },
    )
    _json(
        root / ".engineering-bootstrap/processing-order/release-identity.json",
        {
            "schema_version": "px.release-campaign/1.0",
            "campaign_id": campaign_id,
            "repair_campaign_id": kernel["repair_campaign_id"],
            "state": "active",
            "apply_count": 1,
            "active_claim": None,
            "identity": {**kernel, "release_identity_sha256": identity_sha},
            "stages": {
                "sections": {
                    "status": "passed",
                    "claim_id": f"release-stage:{campaign_id}:sections:fixture",
                    "claimed_at": "2026-09-06T01:00:00Z",
                    "finished_at": "2026-09-06T01:01:00Z",
                },
                "full_profile": {
                    "status": "passed",
                    "claim_id": f"release-stage:{campaign_id}:full_profile:fixture",
                    "claimed_at": "2026-09-06T01:02:00Z",
                    "finished_at": "2026-09-06T01:03:00Z",
                },
                "validate": {
                    "status": "passed",
                    "claim_id": f"release-stage:{campaign_id}:validate:fixture",
                    "claimed_at": "2026-09-06T01:04:00Z",
                    "finished_at": "2026-09-06T01:05:00Z",
                },
                "package": {
                    "status": "passed",
                    "claim_id": package_claim,
                    "claimed_at": "2026-09-06T01:06:00Z",
                    "finished_at": "2026-09-06T01:07:00Z",
                },
                "install": {
                    "status": "passed",
                    "claim_id": install_claim,
                    "claimed_at": "2026-09-06T01:08:00Z",
                    "finished_at": "2026-09-06T01:09:00Z",
                },
                "installed_operational": {
                    "status": "passed",
                    "claim_id": installed_claim,
                    "claimed_at": "2026-09-06T01:10:00Z",
                    "finished_at": "2026-09-06T02:00:00Z",
                },
                "certify": {"status": "pending", "claim_id": None},
            },
        },
    )
    automation_windows = {
        "archive_clear": ("2026-09-06T00:00:00Z", "2026-09-06T00:01:00Z"),
        "reconcile": ("2026-09-06T00:02:00Z", "2026-09-06T00:03:00Z"),
        "identity": ("2026-09-06T00:04:00Z", "2026-09-06T00:05:00Z"),
        "sections": ("2026-09-06T00:59:00Z", "2026-09-06T01:01:00Z"),
        "full_profile": ("2026-09-06T01:01:30Z", "2026-09-06T01:03:00Z"),
        "validate": ("2026-09-06T01:03:30Z", "2026-09-06T01:05:00Z"),
        "package": ("2026-09-06T01:05:30Z", "2026-09-06T01:07:00Z"),
        "install": ("2026-09-06T01:07:30Z", "2026-09-06T01:09:00Z"),
        "installed_operational": (
            "2026-09-06T01:09:30Z",
            "2026-09-06T02:00:00Z",
        ),
    }
    steps: dict[str, object] = {}
    for step in reconciliation.PRIOR_AUTOMATION_STEPS:
        started_utc, finished_utc = automation_windows[step]
        steps[step] = {
            "status": "passed",
            "attempt_count": 1,
            "started_utc": started_utc,
            "finished_utc": finished_utc,
            "gap_id": "PX-OS-1067",
            "admission_event_id": f"admission-{step}",
            "details": {"valid": True},
        }
    steps["card_reconcile"] = {
        "status": "running",
        "attempt_count": 1,
        "started_utc": "2026-09-06T02:01:00Z",
        "gap_id": "PX-OS-1067",
        "admission_event_id": "admission-card-reconcile",
    }
    _json(
        root / AUTOMATION_STATE,
        {
            "schema_version": "px.release-candidate-automation-state/1.0",
            "candidate_id": campaign_id,
            "created_utc": "2026-09-06T00:00:00Z",
            "steps": steps,
        },
    )
    return relative


def test_default_is_a_non_mutating_exact_37_card_plan(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    directory = root / CARD_DIRECTORY
    before = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}

    report = _reconcile(root)
    repeated = _reconcile(root)

    assert report["mode"] == "check"
    assert report["applied"] is False
    assert report["proposed_card_transition_count"] == 37
    assert set(report["proposed_card_ids"]) == SOURCE_CARD_IDS
    assert report["projected_progress"]["downstream_green_source_or_proof_cards"] == 37
    assert report["projected_progress"]["remaining_source_or_proof_cards"] == 0
    assert report == repeated
    assert {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()} == before


def test_current_checksum_and_acceptance_fail_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    card_path = root / CARD_DIRECTORY / "PX-CORE-001.json"
    card_path.write_text(card_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ReconciliationError, match="checksum mismatch"):
        _reconcile(root)

    root = _fixture(tmp_path / "acceptance")
    card_path = root / CARD_DIRECTORY / "PX-CORE-001.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["acceptance_criteria"] = []
    _json(card_path, card)
    _manifest(root / CARD_DIRECTORY)
    with pytest.raises(ReconciliationError, match="acceptance_criteria"):
        _reconcile(root)


def test_dependency_disagreement_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    card_path = root / CARD_DIRECTORY / "PX-CORE-001.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["dependencies"] = []
    _json(card_path, card)
    _manifest(root / CARD_DIRECTORY)
    with pytest.raises(ReconciliationError, match="dependency mismatch"):
        _reconcile(root)


def test_card_specific_live_evidence_and_final99_identity_fail_closed(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)
    finding_path = (
        root
        / "evidence/commencement-audit-20260905T002921Z/finding-dispositions.json"
    )
    finding = json.loads(finding_path.read_text(encoding="utf-8"))
    next(item for item in finding["findings"] if item["id"] == "PX-AUD-012")[
        "disposition"
    ] = "NOT_REPRODUCIBLE"
    _json(finding_path, finding)
    with pytest.raises(ReconciliationError, match="not a live finding"):
        _reconcile(root)

    root = _fixture(tmp_path / "identity")
    identity_path = root / ".engineering-bootstrap/processing-order/release-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["identity"]["source_product_digest"] = "0" * 64
    _json(identity_path, identity)
    with pytest.raises(ReconciliationError, match="final99 release identity is not exact"):
        _reconcile(root)


def test_apply_is_explicit_idempotent_and_hash_binds_evidence(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    applied = _reconcile(root, apply=True, at="2026-09-06T01:00:00Z")
    assert applied["proposed_card_transition_count"] == 37
    assert applied["applied"] is True

    card = json.loads(
        (root / CARD_DIRECTORY / "PX-AGENT-003.json").read_text(encoding="utf-8")
    )
    assert card["status"] == "downstream_green"
    assert len(card["completion_evidence"]) > 4
    assert all("#sha256=" in reference for reference in card["completion_evidence"])
    assert any("#anchor=PX-AUD-007" in reference for reference in card["completion_evidence"])
    assert any("runtime/agent_runtime.py#sha256=" in reference for reference in card["completion_evidence"])
    state = json.loads(
        (root / ".engineering-bootstrap/project-management/state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["checkpoint"]["repository"]["commit"] == OBSERVED_HEAD
    assert state["work"]["active_punch_card"] is None
    assert state["work"]["cohesion_card_summary"]["remaining"] == 0
    assert _reconcile(root, at="2026-09-06T01:00:00Z")["changed_file_count"] == 0


def test_pending_wal_blocks_check_without_mutation_then_apply_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture(tmp_path)
    original_recover = reconciliation.JsonWal.recover
    recover_calls = 0

    def fail_second_recovery(wal: reconciliation.JsonWal) -> dict[str, object]:
        nonlocal recover_calls
        recover_calls += 1
        if recover_calls == 2:
            raise OSError("simulated recovery interruption")
        return original_recover(wal)

    def fail_mid_publish(boundary: str) -> None:
        if boundary == "target:5:published":
            raise OSError("simulated projection interruption")

    monkeypatch.setattr(reconciliation.JsonWal, "recover", fail_second_recovery)
    with pytest.raises(OSError, match="recovery interruption"):
        _reconcile(
            root,
            apply=True,
            at="2026-09-06T01:00:00Z",
            fault_injector=fail_mid_publish,
        )
    monkeypatch.setattr(reconciliation.JsonWal, "recover", original_recover)
    directory = root / CARD_DIRECTORY
    mixed_before_check = {
        path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()
    }
    with pytest.raises(ReconciliationError, match="WAL requires recovery"):
        _reconcile(root)
    assert {
        path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()
    } == mixed_before_check

    recovered = _reconcile(
        root, apply=True, at="2026-09-06T01:00:00Z"
    )
    assert recovered["wal"]["completed"]
    assert recovered["changed_file_count"] == 0
    assert {
        json.loads((directory / f"{card_id}.json").read_text())["status"]
        for card_id in SOURCE_CARD_IDS
    } == {"downstream_green"}
    assert _reconcile(root)["changed_file_count"] == 0


def test_closed_requires_prior_downstream_projection_and_exact_final100_proof(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)
    with pytest.raises(ReconciliationError, match="downstream_green or closed"):
        _reconcile(root, target="closed", installed_proof=Path("not-created.json"))

    _reconcile(root, apply=True, at="2026-09-06T01:00:00Z")
    with pytest.raises(ReconciliationError, match="requires --installed-proof"):
        _reconcile(root, target="closed")

    proof = _installed_proof(root)
    with pytest.raises(ReconciliationError, match="requires --automation-state"):
        _reconcile(root, target="closed", installed_proof=proof)
    report = _reconcile(
        root,
        target="closed",
        installed_proof=proof,
        automation_state=AUTOMATION_STATE,
        at="2026-09-06T02:00:00Z",
    )
    assert report["proposed_card_transition_count"] == 37
    assert report["projected_progress"]["closed_source_or_proof_cards"] == 37
    assert report["projected_progress"]["remaining_source_or_proof_cards"] == 0
    _reconcile(
        root,
        apply=True,
        target="closed",
        installed_proof=proof,
        automation_state=AUTOMATION_STATE,
        at="2026-09-06T02:00:00Z",
    )
    automation_path = root / AUTOMATION_STATE
    automation = json.loads(automation_path.read_text(encoding="utf-8"))
    automation["steps"]["card_reconcile"].update(
        {
            "status": "passed",
            "finished_utc": "2026-09-06T02:01:00Z",
            "details": {"valid": True},
        }
    )
    _json(automation_path, automation)
    repeated = _reconcile(
        root,
        target="closed",
        installed_proof=proof,
        automation_state=AUTOMATION_STATE,
    )
    assert repeated["proposed_card_transition_count"] == 0
    assert repeated["changed_file_count"] == 0


def test_closed_rejects_duplicate_member_and_identity_digest_drift(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)
    _reconcile(root, apply=True, at="2026-09-06T01:00:00Z")
    proof_path = _installed_proof(root)
    absolute = root / proof_path
    proof = json.loads(absolute.read_text(encoding="utf-8"))
    proof["members"].append(dict(proof["members"][0]))
    _json(absolute, proof)
    with pytest.raises(ReconciliationError, match="members are not exact"):
        _reconcile(
            root,
            target="closed",
            installed_proof=proof_path,
            automation_state=AUTOMATION_STATE,
        )

    proof = json.loads(absolute.read_text(encoding="utf-8"))
    proof["members"] = proof["members"][:3]
    proof["source_product_digest"] = "0" * 64
    _json(absolute, proof)
    with pytest.raises(ReconciliationError, match="kernel does not match"):
        _reconcile(
            root,
            target="closed",
            installed_proof=proof_path,
            automation_state=AUTOMATION_STATE,
        )


def test_closed_rejects_self_consistent_unrelated_repair_predecessor(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)
    _reconcile(root, apply=True, at="2026-09-06T01:00:00Z")
    proof_path = _installed_proof(root)
    identity_path = root / ".engineering-bootstrap/processing-order/release-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["repair_campaign_id"] = "pacify-x-unrelated-repair-20260905"
    identity["identity"]["repair_campaign_id"] = identity["repair_campaign_id"]
    kernel = {
        key: value
        for key, value in identity["identity"].items()
        if key != "release_identity_sha256"
    }
    replacement_sha = hashlib.sha256(
        json.dumps(kernel, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    identity["identity"]["release_identity_sha256"] = replacement_sha
    _json(identity_path, identity)
    proof = json.loads((root / proof_path).read_text(encoding="utf-8"))
    proof["release_identity_sha256"] = replacement_sha
    for field in ("package_receipt", "install_receipt"):
        receipt_path = root / proof[field]["path"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["release_identity_sha256"] = replacement_sha
        _json(receipt_path, receipt)
        proof[field]["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        proof[field]["size"] = receipt_path.stat().st_size
    _json(root / proof_path, proof)

    with pytest.raises(ReconciliationError, match="kernel does not match"):
        _reconcile(
            root,
            target="closed",
            installed_proof=proof_path,
            automation_state=AUTOMATION_STATE,
        )


def test_closed_rejects_artifact_split_from_repair12(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _reconcile(root, apply=True, at="2026-09-06T01:00:00Z")
    proof_path = _installed_proof(root)
    alternate = root / "extension/dist/pacify-x-vscode-0.6.86.vsix"
    alternate.write_bytes(b"different-repair12-artifact")
    repair_path = root / DEFAULT_EVIDENCE[3]
    repair = json.loads(repair_path.read_text(encoding="utf-8"))
    repair["immutable_artifact"].update(
        reference="extension/dist/pacify-x-vscode-0.6.86.vsix",
        artifact_sha256=hashlib.sha256(alternate.read_bytes()).hexdigest(),
        artifact_size=alternate.stat().st_size,
    )
    _json(repair_path, repair)

    with pytest.raises(ReconciliationError, match="does not match repair12"):
        _reconcile(
            root,
            target="closed",
            installed_proof=proof_path,
            automation_state=AUTOMATION_STATE,
        )


@pytest.mark.parametrize("receipt_name", ("package_receipt", "install_receipt"))
def test_closed_rejects_legacy_or_drifted_stage_artifact_binding(
    tmp_path: Path, receipt_name: str
) -> None:
    root = _fixture(tmp_path)
    _reconcile(root, apply=True, at="2026-09-06T01:00:00Z")
    proof_path = _installed_proof(root)
    proof = json.loads((root / proof_path).read_text(encoding="utf-8"))
    receipt_path = root / proof[receipt_name]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt_name == "package_receipt":
        receipt["artifact"] = receipt["artifact"]["path"]
    else:
        receipt["artifact"]["sha256"] = "0" * 64
    _json(receipt_path, receipt)
    proof[receipt_name]["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    proof[receipt_name]["size"] = receipt_path.stat().st_size
    _json(root / proof_path, proof)

    with pytest.raises(ReconciliationError, match="evidence does not bind"):
        _reconcile(
            root,
            target="closed",
            installed_proof=proof_path,
            automation_state=AUTOMATION_STATE,
        )


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("release_missing", "stage inventory/order"),
        ("release_failed", "was not passed exactly once"),
        ("release_order", "stage inventory/order"),
        ("automation_missing", "automation stage inventory/order"),
        ("automation_failed", "was not passed exactly once"),
        ("automation_repeated", "was not passed exactly once"),
        ("automation_order", "automation stage inventory/order"),
        ("automation_chronology", "is out of order"),
        ("cross_timeline", "does not enclose its release stage"),
    ),
)
def test_closed_rejects_incomplete_or_replayed_stage_order(
    tmp_path: Path, case: str, message: str
) -> None:
    root = _fixture(tmp_path)
    _reconcile(root, apply=True, at="2026-09-06T01:00:00Z")
    proof_path = _installed_proof(root)
    identity_path = root / ".engineering-bootstrap/processing-order/release-identity.json"
    automation_path = root / AUTOMATION_STATE
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    automation = json.loads(automation_path.read_text(encoding="utf-8"))
    if case == "release_missing":
        identity["stages"].pop("validate")
    elif case == "release_failed":
        identity["stages"]["validate"]["status"] = "failed"
    elif case == "release_order":
        stages = identity["stages"]
        identity["stages"] = {
            "full_profile": stages["full_profile"],
            "sections": stages["sections"],
            **{key: value for key, value in stages.items() if key not in {"sections", "full_profile"}},
        }
    elif case == "automation_missing":
        automation["steps"].pop("validate")
    elif case == "automation_failed":
        automation["steps"]["validate"]["status"] = "failed"
    elif case == "automation_repeated":
        automation["steps"]["validate"]["attempt_count"] = 2
    elif case == "automation_order":
        steps = automation["steps"]
        automation["steps"] = {
            "reconcile": steps["reconcile"],
            "archive_clear": steps["archive_clear"],
            **{key: value for key, value in steps.items() if key not in {"archive_clear", "reconcile"}},
        }
    elif case == "automation_chronology":
        automation["steps"]["validate"]["started_utc"] = "2026-09-06T00:00:00Z"
    else:
        automation["steps"]["sections"]["finished_utc"] = (
            "2026-09-06T00:59:30Z"
        )
    _json(identity_path, identity)
    _json(automation_path, automation)

    with pytest.raises(ReconciliationError, match=message):
        _reconcile(
            root,
            target="closed",
            installed_proof=proof_path,
            automation_state=AUTOMATION_STATE,
        )

@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("campaign", "campaign does not match"),
        ("active_claim", "still has an active claim"),
        ("stage_status", "was not passed exactly once"),
        ("stage_claim", "claim does not match the proof"),
    ),
)
def test_closed_rejects_release_identity_disagreement(
    tmp_path: Path, case: str, message: str
) -> None:
    root = _fixture(tmp_path)
    _reconcile(root, apply=True, at="2026-09-06T01:00:00Z")
    proof = _installed_proof(root)
    identity_path = root / ".engineering-bootstrap/processing-order/release-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if case == "campaign":
        identity["campaign_id"] += "-wrong"
    elif case == "active_claim":
        identity["active_claim"] = "release-stage:still-active"
    elif case == "stage_status":
        identity["stages"]["installed_operational"]["status"] = "failed"
    else:
        identity["stages"]["installed_operational"]["claim_id"] += "-wrong"
    _json(identity_path, identity)

    with pytest.raises(ReconciliationError, match=message):
        _reconcile(
            root,
            target="closed",
            installed_proof=proof,
            automation_state=AUTOMATION_STATE,
        )


@pytest.mark.parametrize(
    "nonzero_field", ("active_processes", "reclaimable_paths", "cleanup_failures")
)
def test_closed_rejects_nonzero_resource_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nonzero_field: str
) -> None:
    root = _fixture(tmp_path)
    _reconcile(root, apply=True, at="2026-09-06T01:00:00Z")
    proof = _installed_proof(root)
    monkeypatch.setattr(
        reconciliation,
        "_resource_status",
        lambda _path: {
            "active_processes": 0,
            "reclaimable_paths": 0,
            "cleanup_failures": 0,
        }
        | {nonzero_field: 1},
    )

    with pytest.raises(ReconciliationError, match="resource status is not clean"):
        _reconcile(
            root,
            target="closed",
            installed_proof=proof,
            automation_state=AUTOMATION_STATE,
        )
