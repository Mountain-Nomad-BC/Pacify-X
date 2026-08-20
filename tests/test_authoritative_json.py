from __future__ import annotations

import json
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

