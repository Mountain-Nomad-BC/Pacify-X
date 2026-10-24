"""Fresh envelope/lineage fixtures; no installed provider or historical evidence."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta

import pytest

from runtime.execution_context import ExecutionContext, execution_context_from_dict


def context():
    return ExecutionContext("run", None, "run", "project", "session", 1, 2, "a" * 64,
        "b" * 64, "c" * 64, "run", (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
        "actor", None, "trace")


def test_roundtrip_and_child_preserve_actual_lineage():
    root = context()
    assert execution_context_from_dict(root.as_dict()) == root
    child = root.child("child", provider_id="service")
    assert child.parent_execution_id == root.execution_id
    assert child.root_execution_id == root.root_execution_id
    assert child.trace_root_id == root.trace_root_id
    assert child.cancellation_scope_id == root.cancellation_scope_id
    assert child.as_dict()["authority_granted"] is False


def test_digest_and_unknown_fields_cannot_be_changed():
    value = context().as_dict()
    value["epoch"] += 1
    with pytest.raises(ValueError, match="digest"):
        execution_context_from_dict(value)
    value = context().as_dict(); value["effect_grants"] = ["write"]
    with pytest.raises(ValueError): execution_context_from_dict(value)


@pytest.mark.parametrize("changes", [{"epoch": True}, {"revision": 0}, {"execution_id": ""},
    {"parent_execution_id": "run"}, {"root_execution_id": "other"}, {"deadline_utc": "2026-10-04T12:00:00"}])
def test_invalid_identity_and_currentness_are_refused(changes):
    with pytest.raises(ValueError): replace(context(), **changes)


def test_stale_epoch_generation_deadline_and_child_extension_are_refused():
    root = context()
    kwargs = dict(project_id="project", session_id="session", epoch=2, generation_vector_sha256="a" * 64)
    root.assert_current(**kwargs)
    with pytest.raises(ValueError): root.assert_current(**{**kwargs, "epoch": 1})
    with pytest.raises(ValueError): root.assert_current(**{**kwargs, "generation_vector_sha256": "d" * 64})
    with pytest.raises(ValueError): root.assert_current(**kwargs, now=datetime.now(timezone.utc) + timedelta(minutes=2))
    with pytest.raises(ValueError): root.child("child", deadline_utc=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
