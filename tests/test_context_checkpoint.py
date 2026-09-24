from __future__ import annotations

import pytest

from runtime.context_checkpoint import PressurePolicy, pressure_action, build_checkpoint, persist_and_publish_checkpoint


def test_context_pressure_thresholds():
    assert pressure_action(69, 100) == "none"
    assert pressure_action(70, 100) == "soft-compaction-checkpoint-consideration"
    assert pressure_action(82, 100) == "checkpoint-required-before-bulk-hydration"
    assert pressure_action(90, 100) == "hard-checkpoint-and-block-bulk-hydration"
    with pytest.raises(ValueError):
        PressurePolicy(.82, .70, .90)


def test_checkpoint_is_bounded_and_sealed():
    packet = build_checkpoint(
        project_id="p", session_id="s", task_id="t", model_route="deep-local", reason="context-pressure",
        decisions=[{"id":"d1","summary":"keep exact evidence"}], goals=[{"id":"g1"}], exact_next_action="continue with test",
        source_usage={"used_tokens": 82, "context_tokens": 100}, source_identity={"provider":"llama.cpp","model":"qwen"},
    )
    assert packet["checkpoint_id"].startswith("ctx-")
    assert len(packet["checkpoint_sha256"]) == 64
    assert packet["authority_granted"] is False


def test_compaction_is_not_permitted_until_persist_and_publish_both_succeed():
    packet = build_checkpoint(project_id="p", session_id="s", task_id=None, model_route="local", reason="handoff")
    persisted = []
    published = []
    receipt = persist_and_publish_checkpoint(
        packet,
        persist=lambda cp: persisted.append(cp["checkpoint_id"]) or {"stored": cp["checkpoint_id"]},
        publish=lambda cp, storage: published.append(storage["stored"]) or {"generation_id":"cg-2"},
    )
    assert receipt["compaction_permitted"] is True
    assert persisted == published

    with pytest.raises(RuntimeError, match="publication"):
        persist_and_publish_checkpoint(packet, persist=lambda cp: {"stored":"yes"}, publish=lambda cp, storage: {})
