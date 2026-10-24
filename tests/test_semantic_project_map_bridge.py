from pathlib import Path
import runtime.semantic_project_map_bridge as bridge

def test_project_map_normalization(monkeypatch, tmp_path: Path):
    def fake(root, query, **kwargs):
        return {"map_revision":"r1", "hits":[{"rank":1,"score":3.0,"id":"s1","kind":"symbol","title":"Engine.run","path":"alpha.py","line_start":2,"line_end":3,"summary":"run engine","reasons":["title:run"],"relations":["s2"]}]}
    monkeypatch.setattr(bridge, "query_project_map", fake)
    raw, evidence = bridge.query_project_map_evidence("p1", tmp_path, "run")
    assert raw["map_revision"] == "r1"
    assert evidence[0].locator == "alpha.py#L2-L3"
    assert evidence[0].source_kind == "project_map"

import pytest


def test_project_map_rejects_nonfinite_scores(monkeypatch, tmp_path: Path):
    def fake(root, query, **kwargs):
        return {"map_revision":"r1", "hits":[{"rank":1,"score":float("nan"),"id":"s1","kind":"symbol","title":"Engine.run","path":"alpha.py","line_start":2,"line_end":3,"summary":"run engine","reasons":[],"relations":[]}]}
    monkeypatch.setattr(bridge, "query_project_map", fake)
    with pytest.raises(ValueError, match="finite"):
        bridge.query_project_map_evidence("p1", tmp_path, "run")
# ---------------------------------------------------------------------------
# Canonical identity through the project-map evidence bridge.
#
# The bridge derived its evidence source_id from stable_id("atlas", project_id,
# hit_id, revision) and carried a raw filesystem path as the locator, with no
# canonical entity identity anywhere. Every downstream consumer therefore had
# nothing but a path- and revision-shaped value to treat as identity.
#
# These pin the repair: canonical identity is resolved through the canonical
# owner and attached alongside the versioned evidence identity, which stays in
# its own domain. Unresolved and ambiguous references must stay explicit.
# ---------------------------------------------------------------------------


class _Entity:
    def __init__(self, entity_id, canonical_entity_id=None):
        self.entity_id = entity_id
        self.canonical_entity_id = canonical_entity_id


class _Map:
    """Minimal canonical owner exposing only the resolver contract."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def resolve_reference(self, reference, *, include_history=False):
        self.calls.append((reference, include_history))
        return tuple(self.table.get(reference, ()))


def _hits(path="alpha.py", hit_id="s1"):
    return {"map_revision": "r1", "hits": [
        {"rank": 1, "score": 3.0, "id": hit_id, "kind": "symbol", "title": "Engine.run",
         "path": path, "line_start": 2, "line_end": 3, "summary": "run engine",
         "reasons": ["title:run"], "relations": ["s2"]}]}


def test_evidence_carries_resolved_canonical_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "query_project_map", lambda *a, **k: _hits())
    semantic_map = _Map({"s1": (_Entity("registry:model:worker-one", "pxe1:worker-one"),)})

    _, evidence = bridge.query_project_map_evidence("p1", tmp_path, "run", semantic_map=semantic_map)

    metadata = evidence[0].metadata
    assert metadata["canonical_entity_id"] == "pxe1:worker-one"
    assert metadata["canonical_resolution"] == "resolved"
    assert metadata["canonical_candidates"] == ["pxe1:worker-one"]


def test_versioned_evidence_identity_is_unchanged_and_separate(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "query_project_map", lambda *a, **k: _hits())
    without = bridge.query_project_map_evidence("p1", tmp_path, "run")[1][0]
    with_map = bridge.query_project_map_evidence(
        "p1", tmp_path, "run",
        semantic_map=_Map({"s1": (_Entity("registry:model:worker-one", "pxe1:worker-one"),)}))[1][0]

    # Attaching canonical identity must not rewrite the evidence identity or
    # silently delete the revision from it. Versioned evidence IDs stay
    # versioned; canonical entity IDs are a separate domain.
    assert with_map.source_id == without.source_id
    assert with_map.revision == without.revision == "r1"
    assert with_map.locator == without.locator == "alpha.py#L2-L3"
    assert with_map.metadata["canonical_entity_id"] != with_map.source_id


def test_unresolved_reference_stays_explicit_and_is_never_guessed(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "query_project_map", lambda *a, **k: _hits())

    _, evidence = bridge.query_project_map_evidence(
        "p1", tmp_path, "run", semantic_map=_Map({}))

    metadata = evidence[0].metadata
    assert metadata["canonical_entity_id"] is None
    assert metadata["canonical_resolution"] == "unresolved"
    assert metadata["canonical_candidates"] == []
    # The evidence itself is still delivered; it is explicitly unowned, not dropped.
    assert evidence[0].locator == "alpha.py#L2-L3"


def test_ambiguous_reference_reports_candidates_instead_of_a_winner(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "query_project_map", lambda *a, **k: _hits())
    semantic_map = _Map({"s1": (_Entity("registry:a", "pxe1:a"), _Entity("registry:b", "pxe1:b"))})

    _, evidence = bridge.query_project_map_evidence("p1", tmp_path, "run", semantic_map=semantic_map)

    metadata = evidence[0].metadata
    assert metadata["canonical_entity_id"] is None
    assert metadata["canonical_resolution"] == "ambiguous"
    assert metadata["canonical_candidates"] == ["pxe1:a", "pxe1:b"]


def test_path_is_used_for_resolution_only_after_the_declared_id(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "query_project_map", lambda *a, **k: _hits())
    semantic_map = _Map({"alpha.py": (_Entity("registry:by-path", "pxe1:by-path"),)})

    _, evidence = bridge.query_project_map_evidence("p1", tmp_path, "run", semantic_map=semantic_map)

    # The declared hit id is tried first; the path is only a fallback reference.
    assert semantic_map.calls[0][0] == "s1"
    assert evidence[0].metadata["canonical_entity_id"] == "pxe1:by-path"


def test_history_is_opt_in_and_never_implicit(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "query_project_map", lambda *a, **k: _hits())
    semantic_map = _Map({"alpha.py": (_Entity("registry:historic"),)})

    bridge.query_project_map_evidence("p1", tmp_path, "run", semantic_map=semantic_map)
    assert semantic_map.calls[0][1] is False

    semantic_map.calls.clear()
    bridge.query_project_map_evidence(
        "p1", tmp_path, "run", semantic_map=semantic_map, include_history=True)
    assert semantic_map.calls[0][1] is True


def test_no_map_supplied_is_explicit_not_attempted(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "query_project_map", lambda *a, **k: _hits())

    _, evidence = bridge.query_project_map_evidence("p1", tmp_path, "run")

    assert evidence[0].metadata["canonical_resolution"] == "not_attempted"
    assert evidence[0].metadata["canonical_entity_id"] is None


def test_history_flag_must_be_an_explicit_boolean(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "query_project_map", lambda *a, **k: _hits())

    with pytest.raises(ValueError, match="include_history"):
        bridge.query_project_map_evidence(
            "p1", tmp_path, "run", include_history="yes")

def test_projection_id_without_canonical_binding_is_not_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "query_project_map", lambda *a, **k: _hits())
    _, evidence = bridge.query_project_map_evidence(
        "p1", tmp_path, "run",
        semantic_map=_Map({"s1": (_Entity("registry:model:worker-one"),)}))
    assert evidence[0].metadata["canonical_entity_id"] is None
    assert evidence[0].metadata["canonical_resolution"] == "unresolved"
