from __future__ import annotations

from dataclasses import replace

from runtime.semantic_memory import (
    MAX_PAYLOAD_DEPTH,
    SemanticEntity,
    SemanticEnvelope,
    SemanticRelation,
    semantic_envelope_from_mapping,
    semantic_index_projection,
    semantic_query_signals,
)


def envelope() -> SemanticEnvelope:
    return SemanticEnvelope(
        namespace="project:prj-alpha",
        record_type="procedure",
        payload={"instruction": "Run the bounded verification gate."},
        exact_keys=("gate-alpha", "verification-gate"),
        aliases=("bounded check", "gate check"),
        tags=("verification", "release"),
        entities=(
            SemanticEntity("procedure:gate-alpha", "procedure", ("gate",)),
            SemanticEntity("artifact:receipt-alpha", "evidence", ("receipt",)),
        ),
        relations=(
            SemanticRelation(
                "procedure:gate-alpha",
                "PRODUCES",
                "artifact:receipt-alpha",
                0.9,
                "evidence:test-fixture",
            ),
        ),
        required_context={"phase": "verification"},
        excluded_context={"phase": "draft"},
        validation_checks=("source_bound", "project_bound"),
    )


def test_canonical_identity_is_stable_for_unordered_semantic_sets() -> None:
    original = envelope()
    reordered = replace(
        original,
        exact_keys=tuple(reversed(original.exact_keys)),
        aliases=tuple(reversed(original.aliases)),
        tags=tuple(reversed(original.tags)),
        entities=tuple(reversed(original.entities)),
        validation_checks=tuple(reversed(original.validation_checks)),
    )
    assert reordered.canonical_mapping() == original.canonical_mapping()
    assert reordered.canonical_sha256() == original.canonical_sha256()


def test_mapping_round_trip_preserves_canonical_semantics() -> None:
    original = envelope()
    hydrated = semantic_envelope_from_mapping(original.canonical_mapping())
    assert hydrated.canonical_mapping() == original.canonical_mapping()
    assert hydrated.validation_errors(project_id="prj-alpha") == ()


def test_cross_project_namespace_and_dangling_graph_edges_fail_closed() -> None:
    assert "semantic_namespace_crosses_project" in replace(
        envelope(), namespace="project:other"
    ).validation_errors(project_id="prj-alpha")
    dangling = replace(
        envelope(),
        relations=(
            SemanticRelation(
                "procedure:gate-alpha",
                "PRODUCES",
                "artifact:missing",
                1.0,
                "evidence:test-fixture",
            ),
        ),
    )
    assert "semantic_relation_dangling" in dangling.validation_errors(
        project_id="prj-alpha"
    )


def test_payload_limits_are_enforced() -> None:
    nested: object = "leaf"
    for _ in range(MAX_PAYLOAD_DEPTH + 2):
        nested = {"next": nested}
    errors = replace(envelope(), payload={"root": nested}).validation_errors(
        project_id="prj-alpha"
    )
    assert "semantic_payload_depth_limit" in errors


def test_exact_route_precedes_overlap_and_projection_excludes_payload() -> None:
    exact_priority, exact_score = semantic_query_signals(
        "use gate alpha for this release", envelope()
    )
    fuzzy_priority, fuzzy_score = semantic_query_signals("release", envelope())
    assert exact_priority == 0
    assert exact_score > fuzzy_score
    assert fuzzy_priority == 1
    projection = semantic_index_projection(envelope())
    assert "payload" not in projection
    assert len(projection["semantic_sha256"]) == 64
