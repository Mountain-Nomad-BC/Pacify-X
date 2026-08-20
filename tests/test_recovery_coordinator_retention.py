from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from runtime.recovery import (
    RecoveryConfiguration,
    RecoveryCoordinator,
    choose_recovery,
)
from runtime.resource_lifecycle import (
    OPERATIONAL_HISTORY_SCHEMA_VERSION,
    ResourceClassification,
    ResourceManager,
    RetentionManager,
    RunState,
    retention_policy,
)
from runtime.wal_transaction import JsonArtifact, JsonWal


FIXTURES = Path(__file__).parent / "fixtures" / "durable_state"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _history(count: int) -> dict[str, object]:
    previous = None
    records: list[dict[str, object]] = []
    for sequence in range(1, count + 1):
        record: dict[str, object] = {
            "sequence": sequence,
            "previous_record_sha256": previous,
            "payload": {"event": sequence},
        }
        digest = hashlib.sha256(_canonical(record)).hexdigest()
        record["record_sha256"] = digest
        records.append(record)
        previous = digest
    return {
        "schema_version": OPERATIONAL_HISTORY_SCHEMA_VERSION,
        "anchor": None,
        "records": records,
    }


def test_recovery_decisions_are_bounded_and_denials_never_retry() -> None:
    retry = choose_recovery(
        failure_class="transient",
        failure_signature="network-timeout",
        trace_signatures=("network-timeout",),
        attempts=1,
        retry_budget=3,
        idempotent=True,
    )
    assert retry.action == "retry"
    assert retry.retry_remaining == 1
    assert retry.forensic_state == "retained"

    opened = choose_recovery(
        failure_class="transient",
        failure_signature="same",
        trace_signatures=("same", "same", "same"),
        attempts=1,
        retry_budget=10,
        idempotent=True,
    )
    assert opened.action == "escalate"
    assert opened.circuit_open is True

    denial = choose_recovery(
        failure_class="policy_denial",
        failure_signature="denied",
        trace_signatures=(),
        attempts=0,
        retry_budget=10,
        idempotent=True,
        fallbacks=("rephrase",),
    )
    assert denial.action == "stop"
    assert denial.fallback is None


def test_coordinator_recovers_interrupted_wal_and_is_repeatable(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    wal_root = tmp_path / "wal"
    wal = JsonWal(wal_root, tmp_path)

    def interrupt(boundary: str) -> None:
        if boundary == "target:0:published":
            raise RuntimeError("simulated process interruption")

    with pytest.raises(RuntimeError, match="simulated"):
        wal.commit(
            (JsonArtifact("state", target, {"revision": 1}),),
            transaction_id="interrupted",
            fault_injector=interrupt,
        )
    coordinator = RecoveryCoordinator(
        RecoveryConfiguration(tmp_path, wal_targets=((wal_root, tmp_path),))
    )
    inspection = coordinator.reconcile()
    assert inspection["status"] == "degraded"
    assert inspection["components"][0]["detail"]["requires_recovery"] is True
    assert not (wal_root / "committed" / "interrupted").exists()
    first = coordinator.reconcile(apply=True)
    second = coordinator.reconcile(apply=True)
    assert first["status"] == "healthy"
    assert second["status"] == "healthy"
    assert json.loads(target.read_text(encoding="utf-8")) == {"revision": 1}


def test_retention_never_auto_purges_evidence_or_ambiguity(tmp_path: Path) -> None:
    manager = ResourceManager(tmp_path / "state" / "resources.json")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    record = manager.register_path(
        evidence,
        allowed_cleanup_root=tmp_path,
        project_id="project",
        run_id="evidence-run",
        lane_id="lane",
        creator="test",
        classification=ResourceClassification.EVIDENCE,
    )
    manager.mark_run_ended(record.run_id, RunState.COMPLETED)
    retention = RetentionManager(
        manager,
        allowed_root=tmp_path,
        wal_root=tmp_path / ".retention-wal",
    )
    receipt = retention.reclaim_transient(
        record.resource_id, reason="pressure", apply=True
    )
    assert receipt.resources_reclaimed == 0
    assert evidence.is_dir()
    assert retention_policy("unclassified")["action"] == "retain"
    assert retention_policy("unclassified")["retention_class"] == "unknown"


def test_transient_cleanup_requires_registered_ephemeral_safe_gate(
    tmp_path: Path,
) -> None:
    manager = ResourceManager(tmp_path / "state" / "resources.json")
    record = manager.create_workspace(
        tmp_path,
        project_id="project",
        run_id="run",
        lane_id="lane",
        creator="test",
    )
    target = Path(record.path or "")
    (target / "scratch.txt").write_text("temporary", encoding="utf-8")
    manager.mark_run_ended(record.run_id, RunState.COMPLETED)
    retention = RetentionManager(
        manager,
        allowed_root=tmp_path,
        wal_root=tmp_path / ".retention-wal",
    )
    receipt = retention.reclaim_transient(
        record.resource_id, reason="run ended", apply=True
    )
    assert receipt.resources_reclaimed == 1
    assert not target.exists()
    assert (manager.receipt_dir / f"{receipt.cleanup_id}.json").is_file()


def test_operational_pruning_retains_anchor_and_receipt(tmp_path: Path) -> None:
    history_path = tmp_path / "operations.json"
    history_path.write_bytes(_canonical(_history(5)))
    manager = ResourceManager(tmp_path / "state" / "resources.json")
    retention = RetentionManager(
        manager,
        allowed_root=tmp_path,
        wal_root=tmp_path / ".retention-wal",
        receipt_dir=tmp_path / "retention-evidence",
    )
    dry_run = retention.prune_operational_history(history_path, max_records=2)
    assert dry_run["records_pruned"] == 3
    assert dry_run["applied"] is False
    assert len(json.loads(history_path.read_text(encoding="utf-8"))["records"]) == 5

    applied = retention.prune_operational_history(
        history_path, max_records=2, apply=True
    )
    retained = json.loads(history_path.read_text(encoding="utf-8"))
    assert retained["anchor"]["through_sequence"] == 3
    assert [item["sequence"] for item in retained["records"]] == [4, 5]
    assert (
        retained["records"][0]["previous_record_sha256"]
        == retained["anchor"]["head_sha256"]
    )
    assert Path(applied["anchor_path"]).is_file()
    receipt_path = tmp_path / "retention-evidence" / f"{applied['receipt_id']}.json"
    assert receipt_path.is_file()
    assert applied["ancestry_preserved"] is True


def test_doctor_reports_healthy_degraded_and_blocked(tmp_path: Path) -> None:
    healthy = RecoveryCoordinator(RecoveryConfiguration(tmp_path)).reconcile()
    assert healthy["status"] == "healthy"
    assert healthy["valid"] is True
    assert healthy["human_summary"].startswith("Recovery doctor: healthy")

    legacy = tmp_path / "durable.json"
    shutil.copyfile(FIXTURES / "legacy-unversioned.json", legacy)
    degraded = RecoveryCoordinator(
        RecoveryConfiguration(tmp_path, durable_state_paths=(legacy,))
    ).reconcile()
    assert degraded["status"] == "degraded"
    assert legacy.read_bytes() == (FIXTURES / "legacy-unversioned.json").read_bytes()

    blocked = RecoveryCoordinator(
        RecoveryConfiguration(
            tmp_path,
            event_bus_reconcilers=(
                lambda apply: {
                    "valid": False,
                    "errors": ["gap"],
                    "apply": apply,
                },
            ),
        )
    ).reconcile()
    assert blocked["status"] == "blocked"
    assert blocked["forensic_state"] == "retained"


def test_doctor_apply_migrates_legacy_with_retained_receipt(tmp_path: Path) -> None:
    state = tmp_path / "durable.json"
    shutil.copyfile(FIXTURES / "1.0.json", state)
    report = RecoveryCoordinator(
        RecoveryConfiguration(tmp_path, durable_state_paths=(state,))
    ).reconcile(apply=True)
    assert report["status"] == "healthy"
    assert json.loads(state.read_text(encoding="utf-8"))["schema_version"] == "2.0"
    receipts = tuple(
        (tmp_path / ".migrations" / "durable.json" / "receipts").glob("*.json")
    )
    assert len(receipts) == 1
