import json
from pathlib import Path

import pytest
from runtime.local_model_runtime import LocalModelRuntime
from runtime.vscode_model_bridge import _event_rows


def native_event(root):
    runtime = LocalModelRuntime(root, allowed_model_roots=(root,), allowed_runtime_roots=(root,))
    return runtime._append('controlled-discovery', {'fixture': True})


def test_bridge_discovers_events_written_by_actual_current_runtime_owner(tmp_path):
    event = native_event(tmp_path)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*'))
    assert _event_rows(tmp_path) == [event]
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*')) == before


def test_canonical_log_wins_without_merging_legacy_history(tmp_path):
    event = native_event(tmp_path)
    target = tmp_path / '.agentic_engineering_os_px/local-model-runtime/events.jsonl'
    target.parent.mkdir(parents=True)
    target.write_text('', encoding='utf-8')
    assert _event_rows(tmp_path) == []
    target.write_text(json.dumps(event) + '\n', encoding='utf-8')
    assert _event_rows(tmp_path) == [event]


def test_invalid_canonical_history_is_not_replaced_with_old_history(tmp_path):
    event = native_event(tmp_path)
    target = tmp_path / '.agentic_engineering_os_px/local-model-runtime/events.jsonl'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({**event, 'payload': {'rebound': True}}), encoding='utf-8')
    with pytest.raises(ValueError, match='chain'):
        _event_rows(tmp_path)
