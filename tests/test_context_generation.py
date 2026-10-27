import hashlib

import pytest

from runtime.context_generation import COMPONENTS, context_vector, read_context_vector


def components():
    return {name: hashlib.sha256(name.encode()).hexdigest() for name in COMPONENTS}


def test_vector_order_is_irrelevant_and_dependency_change_invalidates_it():
    values = components()
    first = context_vector("px", "chat", values)
    assert first.vector_sha256 == context_vector("px", "chat", dict(reversed(list(values.items())))).vector_sha256
    changed = {**values, "policy_revision": hashlib.sha256(b"changed policy").hexdigest()}
    assert first.vector_sha256 != context_vector("px", "chat", changed).vector_sha256
    assert first.vector_sha256 != context_vector("other", "chat", values).vector_sha256
    assert first.vector_sha256 != context_vector("px", "other", values).vector_sha256


def test_missing_components_are_explicit_and_round_trip_cannot_forge_hash():
    vector = context_vector("px", "metadata", {"source_revision": "r1"}, required_components=("source_revision",))
    assert vector.components["model_fabric_generation"] is None
    record = vector.as_mapping()
    assert read_context_vector(record) == vector
    record["vector"]["source_revision"] = "r2"
    with pytest.raises(ValueError, match="digest"):
        read_context_vector(record)


@pytest.mark.parametrize("values", [{"unknown": "r1"}, {"source_revision": ""}, {"source_revision": 1}, {"source_revision": "x" * 513}])
def test_malformed_or_unbounded_component_cannot_enter_vector(values):
    with pytest.raises(ValueError):
        context_vector("px", "metadata", values)


def test_mutating_input_or_serialized_projection_cannot_change_live_vector():
    values = components()
    vector = context_vector("px", "chat", values)
    identity = vector.vector_sha256
    values["source_revision"] = "changed"
    record = vector.as_mapping()
    record["vector"]["source_revision"] = "changed"
    assert vector.vector_sha256 == identity
    assert vector.components["source_revision"] != "changed"


def test_registered_dependency_owner_projects_exact_bindings_without_guessing_absence():
    from runtime.dependency_invalidation import context_vector_for_dependencies
    revisions = {"source:a": "r1", "policy:a": None}
    bindings = {"source_revision": ["source:a"], "policy_revision": ["policy:a"]}
    before = context_vector_for_dependencies("px", "metadata", revisions, bindings, required_components=("source_revision",))
    assert before.components["policy_revision"] is None
    after = context_vector_for_dependencies("px", "metadata", {**revisions, "source:a": "r2"}, bindings, required_components=("source_revision",))
    assert before.vector_sha256 != after.vector_sha256
    with pytest.raises(ValueError, match="unknown or duplicate"):
        context_vector_for_dependencies("px", "metadata", revisions, {"source_revision": ["missing"]}, required_components=("source_revision",))
