from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import runtime.authoritative_json as authoritative_json
from runtime.authoritative_json import AuthoritativeStateError, load_classified_json


ROOT = Path(__file__).resolve().parents[1]


def test_valid_authoritative_json_loads_without_fallback(tmp_path: Path) -> None:
    state = tmp_path / "workspace.json"
    state.write_text('{"schema_version":"1.0"}', encoding="utf-8")
    result = load_classified_json(
        ROOT,
        state,
        artifact_kind="workspace_registry",
        allowed_root=tmp_path,
        quarantine_root=tmp_path / "quarantine",
    )
    assert result["status"] == "valid"
    assert result["data"] == {"schema_version": "1.0"}


def test_corrupt_authoritative_json_is_preserved_and_fails_closed(tmp_path: Path) -> None:
    state = tmp_path / "workspace.json"
    original = b'{"broken":'
    state.write_bytes(original)
    with pytest.raises(AuthoritativeStateError) as captured:
        load_classified_json(
            ROOT,
            state,
            artifact_kind="workspace_registry",
            allowed_root=tmp_path,
            quarantine_root=tmp_path / "quarantine",
        )
    assert not state.exists()
    receipt_path = captured.value.receipt
    assert receipt_path is not None and receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    quarantined = Path(receipt["quarantined_path"])
    assert quarantined.read_bytes() == original
    assert receipt["decision"] == "quarantined_fail_closed"
    intent_path = Path(str(quarantined) + ".intent.json")
    assert intent_path.is_file()
    intent_bytes = intent_path.read_bytes()
    assert receipt["intent_sha256"] == hashlib.sha256(intent_bytes).hexdigest()


def test_derived_corruption_requires_rebuild_and_preserves_source(tmp_path: Path) -> None:
    state = tmp_path / "sidebar.json"
    state.write_text("not-json", encoding="utf-8")
    result = load_classified_json(
        ROOT,
        state,
        artifact_kind="dashboard_snapshot",
        allowed_root=tmp_path,
        quarantine_root=tmp_path / "quarantine",
    )
    assert result["status"] == "rebuild_required"
    assert state.read_text(encoding="utf-8") == "not-json"


def test_unclassified_state_is_refused(tmp_path: Path) -> None:
    state = tmp_path / "unknown.json"
    state.write_text("{}", encoding="utf-8")
    with pytest.raises(AuthoritativeStateError, match="unclassified"):
        load_classified_json(
            ROOT,
            state,
            artifact_kind="mystery",
            allowed_root=tmp_path,
            quarantine_root=tmp_path / "quarantine",
        )


def test_changed_snapshot_refuses_quarantine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "workspace.json"
    state.write_text("not-json", encoding="utf-8")
    original_snapshot = authoritative_json._snapshot
    calls = 0

    def changed(path: Path) -> dict[str, object]:
        nonlocal calls
        result = original_snapshot(path)
        calls += 1
        if calls == 2:
            result["mtime_ns"] = int(result["mtime_ns"]) + 1
        return result

    monkeypatch.setattr(authoritative_json, "_snapshot", changed)
    with pytest.raises(AuthoritativeStateError, match="changed"):
        load_classified_json(
            ROOT,
            state,
            artifact_kind="workspace_registry",
            allowed_root=tmp_path,
            quarantine_root=tmp_path / "quarantine",
        )
    assert state.exists()


def test_path_identity_swap_after_immediate_snapshot_is_recovery_receipted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "workspace.json"
    original = b'{"broken":'
    state.write_bytes(original)
    twin = tmp_path / "same-bytes-twin.json"
    twin.write_bytes(original)
    original_held = tmp_path / "original-held.json"
    original_replace = os.replace
    swapped = False

    def swap_path_then_move(source: object, destination: object) -> None:
        nonlocal swapped
        source_path = Path(source)
        if source_path == state and not swapped:
            swapped = True
            original_replace(state, original_held)
            original_replace(twin, state)
        original_replace(source, destination)

    monkeypatch.setattr(authoritative_json.os, "replace", swap_path_then_move)
    with pytest.raises(AuthoritativeStateError, match="recovery") as captured:
        load_classified_json(
            ROOT,
            state,
            artifact_kind="workspace_registry",
            allowed_root=tmp_path,
            quarantine_root=tmp_path / "quarantine",
        )
    assert swapped is True
    assert original_held.read_bytes() == original
    recovery_path = captured.value.receipt
    assert recovery_path is not None and recovery_path.is_file()
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    assert recovery["decision"] == "quarantine_recovery_required"
    assert recovery["failure"] == "filesystem_identity_mismatch"
    assert Path(recovery["custody_path"]).read_bytes() == original


def test_receipt_write_failure_retains_moved_custody_and_recovery_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "workspace.json"
    original = b'{"broken":'
    state.write_bytes(original)
    original_write_record = authoritative_json._write_record

    def fail_final_receipt(path: Path, record: object) -> str:
        if path.name.endswith(".receipt.json"):
            raise OSError("injected receipt failure")
        return original_write_record(path, record)  # type: ignore[arg-type]

    monkeypatch.setattr(authoritative_json, "_write_record", fail_final_receipt)
    with pytest.raises(AuthoritativeStateError, match="recovery") as captured:
        load_classified_json(
            ROOT,
            state,
            artifact_kind="workspace_registry",
            allowed_root=tmp_path,
            quarantine_root=tmp_path / "quarantine",
        )
    assert not state.exists()
    recovery_path = captured.value.receipt
    assert recovery_path is not None and recovery_path.is_file()
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    assert recovery["decision"] == "quarantine_recovery_required"
    assert recovery["failure"] == "receipt_write_failed"
    assert Path(recovery["custody_path"]).read_bytes() == original
