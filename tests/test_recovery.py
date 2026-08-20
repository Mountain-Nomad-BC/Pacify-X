from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import tempfile

import pytest

from runtime.recovery import (
    CURRENT_STATE_SCHEMA_VERSION,
    DurableState,
    DurableStateIntegrityError,
    DurableStateVersionError,
    load_state,
    migrate_state,
    persist_state,
    reconcile_resume,
)


FIXTURES = Path(__file__).parent / "fixtures" / "durable_state"


def _state(*, interrupted: tuple[str, ...] = ()) -> DurableState:
    return DurableState(
        package_id="pkg-1",
        completed_steps=("plan",),
        selected_skills=(("skill-a", "1.0"),),
        pending_approvals=("approval-1",),
        evidence_refs=("evidence-1",),
        idempotency_keys=("effect-1",),
        interrupted_steps=interrupted,
    )


def test_durable_state_round_trip_and_previous_version_is_preserved() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state/state.json"
        persist_state(_state(), path)
        assert load_state(path) == _state()
        persist_state(_state(interrupted=("execute",)), path)
        history = list((path.parent / ".history/state.json").glob("*.json"))
        assert len(history) == 1
        assert load_state(history[0]) == _state()
        assert load_state(path) == _state(interrupted=("execute",))


def test_every_supported_version_has_a_fixture_and_migrates_or_loads() -> None:
    assert {path.stem for path in FIXTURES.glob("[0-9]*.json")} == {"1.0", "2.0"}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        current = root / "current.json"
        shutil.copyfile(FIXTURES / "2.0.json", current)
        assert load_state(current).package_id == "fixture-v2"
        result = migrate_state(current)
        assert result["migrated"] is False
        assert result["reason"] == "already_current"

        old = root / "old.json"
        shutil.copyfile(FIXTURES / "1.0.json", old)
        with pytest.raises(DurableStateVersionError, match="explicit migration"):
            load_state(old)
        receipt = migrate_state(old)
        assert receipt["from_version"] == "1.0"
        assert receipt["to_version"] == CURRENT_STATE_SCHEMA_VERSION
        assert load_state(old).interrupted_steps == ()


def test_migration_preserves_exact_backup_and_retains_receipt() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.json"
        source = (FIXTURES / "legacy-unversioned.json").read_bytes()
        path.write_bytes(source)
        receipt = migrate_state(path)
        backup = json.loads(
            Path(str(receipt["backup_path"])).read_text(encoding="utf-8")
        )
        assert base64.b64decode(backup["source_bytes_base64"]) == source
        receipt_path = (
            path.parent
            / ".migrations"
            / path.name
            / "receipts"
            / f"{receipt['migration_id']}.json"
        )
        retained = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert retained == receipt
        assert load_state(path).interrupted_steps == ("execute",)


def test_migration_is_idempotent_and_does_not_duplicate_evidence() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.json"
        shutil.copyfile(FIXTURES / "1.0.json", path)
        first = migrate_state(path)
        second = migrate_state(path)
        root = path.parent / ".migrations" / path.name
        assert first["migrated"] is True
        assert second["migrated"] is False
        assert len(list((root / "backups").glob("*.json"))) == 1
        assert len(list((root / "receipts").glob("*.json"))) == 1


@pytest.mark.parametrize("version", ["3.0", "999.0"])
def test_newer_state_refuses_load_migration_and_persist(version: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.json"
        payload = json.loads((FIXTURES / "2.0.json").read_text(encoding="utf-8"))
        payload["schema_version"] = version
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(DurableStateVersionError, match="downgrade refused"):
            load_state(path)
        with pytest.raises(DurableStateVersionError, match="downgrade refused"):
            migrate_state(path)
        with pytest.raises(DurableStateVersionError, match="downgrade refused"):
            persist_state(_state(), path)


def test_explicit_downgrade_and_unsupported_versions_are_refused() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.json"
        shutil.copyfile(FIXTURES / "2.0.json", path)
        with pytest.raises(DurableStateVersionError, match="downgrade refused"):
            migrate_state(path, target_version="1.0")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema_version"] = "0.9"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(DurableStateVersionError, match="unsupported"):
            migrate_state(path)


def test_malformed_or_extra_fields_fail_closed_without_backup_or_receipt() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.json"
        path.write_text('{"schema_version":"1.0","unexpected":true}', encoding="utf-8")
        with pytest.raises(DurableStateIntegrityError, match="fields are not exact"):
            migrate_state(path)
        migration_root = path.parent / ".migrations" / path.name
        assert not (migration_root / "backups").exists()
        assert not (migration_root / "receipts").exists()


def test_durable_state_refuses_non_file_replacement_target() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state"
        path.mkdir()
        with pytest.raises(ValueError, match="not a file"):
            persist_state(_state(), path)


def test_resume_fails_for_missing_evidence_interruption_and_replayed_effect() -> None:
    allowed, reasons = reconcile_resume(
        _state(interrupted=("execute",)),
        actual_evidence=(),
        requested_idempotency_key="effect-1",
    )
    assert not allowed
    assert reasons == (
        "effect idempotency key has already completed",
        "interrupted steps are non-certifying",
        "recorded evidence is missing from runtime",
    )


def test_resume_accepts_current_evidence_and_new_effect_key() -> None:
    assert reconcile_resume(
        _state(),
        actual_evidence=("evidence-1",),
        requested_idempotency_key="effect-2",
    ) == (True, ())
