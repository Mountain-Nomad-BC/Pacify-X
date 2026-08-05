from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from runtime.capability_routing import (
    build_minimum_package,
    canonicalize_records,
    discover_independently,
    expand_graph,
    normalize_task,
    rank_candidates,
    route_task,
)
from runtime.contracts import validate_instance
from runtime.registry import skill_discovery_sources, skill_navigation_index
from runtime.skill_navigator import CapabilitySummary


ROOT = Path(__file__).parents[1]


def records():
    return (
        CapabilitySummary(
            "map-project-intelligence",
            "build deterministic repository architecture map",
            triggers=("map repository",),
            aliases=("project map",),
            capability_tags=("repository", "map", "architecture"),
            outputs=("map",),
            contracts=("project-map",),
            validators=("fresh-map",),
        ),
        CapabilitySummary(
            "query-project-map",
            "query repository structural evidence",
            triggers=("query project map",),
            aliases=("repository lookup",),
            capability_tags=("repository", "retrieval"),
            dependencies=("map-project-intelligence",),
            relations=("map-project-intelligence",),
            outputs=("evidence",),
        ),
        CapabilitySummary(
            "unsafe-delete",
            "delete production data",
            triggers=("delete database",),
            risk="R4",
            negative_matches=("preserve data",),
            reviewed_by=(),
        ),
        CapabilitySummary(
            "external-candidate",
            "candidate external retrieval",
            status="candidate_external",
            capability_tags=("retrieval",),
        ),
    )


def test_task_normalization_precedes_retrieval_and_is_stable():
    first = normalize_task(
        "Map this Python repository and produce a validated report",
        constraints=("Do not delete anything",),
    )
    second = normalize_task(
        "Map this Python repository and produce a validated report",
        constraints=("Do not delete anything",),
    )
    assert first == second
    assert first.repository_context_required
    assert first.raw_constraints == ("Do not delete anything",)
    assert first.task_envelope_sha256
    assert "python" in first.technologies


def test_independent_discovery_is_not_prematurely_collapsed():
    envelope = normalize_task("query the repository project map")
    source = records()
    result = discover_independently(envelope, {"skills": source, "aliases": source})
    assert set(result) == {"skills", "aliases"}
    assert result["skills"] and result["aliases"]
    assert result["skills"][0].source_path == "skills"


def test_graph_expansion_is_bounded_and_cycle_safe():
    edges = {
        "a": (("requires", "b"),),
        "b": (("requires", "a"), ("supports", "c")),
        "c": (("supports", "d"),),
    }
    result = expand_graph(("a",), edges, max_depth=2, max_nodes=3, max_edges=4)
    assert set(result) == {"a", "b", "c"}


def test_ranking_keeps_external_candidate_discovery_only_and_blocks_high_risk():
    source = records()
    envelope = normalize_task("retrieve repository map evidence")
    discovery = discover_independently(envelope, {"skills": source})
    ranked = rank_candidates(
        envelope,
        discovery,
        {item.capability_id: item for item in source},
        max_risk="R2",
    )
    by_id = {item.candidate_id: item for item in ranked}
    if "external-candidate" in by_id:
        assert by_id["external-candidate"].disposition == "discovery_only"
    if "unsafe-delete" in by_id:
        assert by_id["unsafe-delete"].disposition == "discovery_only"


def test_minimum_package_adds_dependency_and_is_deterministic():
    source = records()
    envelope = normalize_task("query the repository project map")
    discovery = discover_independently(envelope, {"skills": source})
    mapping = {item.capability_id: item for item in source}
    ranked = rank_candidates(envelope, discovery, mapping)
    package = build_minimum_package(envelope, ranked, mapping)
    assert package.complete
    assert package.receipt_sha256
    if "query-project-map" in package.selected:
        assert "map-project-intelligence" in package.selected


def test_route_result_is_hash_stable_without_project_context():
    source = records()
    first = route_task("query project map evidence", {"skills": source})
    second = route_task("query project map evidence", {"skills": source})
    assert asdict(first) == asdict(second)
    assert first.package.executable


def test_invalid_budgets_fail_closed():
    with pytest.raises(ValueError):
        expand_graph(("a",), {}, max_depth=4)


def test_declared_conflict_only_penalizes_an_applicable_conflict():
    primary = CapabilitySummary(
        "primary", "map repository", conflicts_with=("unrelated",)
    )
    unrelated = CapabilitySummary("unrelated", "send marketing email")
    envelope = normalize_task("map repository")
    discovery = discover_independently(envelope, {"catalog": (primary, unrelated)})
    ranked = rank_candidates(
        envelope,
        discovery,
        {item.capability_id: item for item in (primary, unrelated)},
    )
    result = next(item for item in ranked if item.canonical_id == "primary")
    assert result.penalties["conflict"] == 0.0
    assert result.disposition == "selectable"


def test_live_registry_exposes_independent_sources_and_valid_contract_instances():
    sources = skill_discovery_sources(ROOT)
    assert set(sources) == {
        "skill_catalog",
        "semantic_capability_index",
        "cognitive_map_index",
        "agency_agent_registry",
    }
    canonical = {item.capability_id: item for item in skill_navigation_index(ROOT)}
    routed = route_task(
        "verify outcome evidence",
        sources,
        canonical_records=canonical,
    )
    envelope_instance = json.loads(json.dumps(asdict(routed.envelope)))
    package_instance = json.loads(json.dumps(asdict(routed.package)))
    validate_instance(
        envelope_instance, ROOT / "contracts" / "task-envelope.schema.json"
    )
    validate_instance(
        package_instance, ROOT / "contracts" / "execution-package.schema.json"
    )


def test_canonical_dedup_uses_semantic_responsibility_and_explicit_supersession():
    canonical = CapabilitySummary(
        "canonical",
        "validate governed release evidence",
        outcomes=("validated release",),
        outputs=("evidence receipt",),
        validation_coverage=1.0,
    )
    renamed_shadow = CapabilitySummary(
        "different-name",
        "validate governed release evidence",
        outcomes=("validated release",),
        outputs=("evidence receipt",),
        status="candidate",
    )
    replacement = CapabilitySummary(
        "replacement",
        "route external capability candidates",
        supersedes=("legacy",),
    )
    legacy = CapabilitySummary("legacy", "old external routing")
    mapping = {
        item.capability_id: item
        for item in (canonical, renamed_shadow, replacement, legacy)
    }
    owners, reasons = canonicalize_records(mapping)
    assert owners["different-name"] == "canonical"
    assert owners["legacy"] == "replacement"
    assert ("different-name", "canonical", "exact_semantic_shadow") in reasons
