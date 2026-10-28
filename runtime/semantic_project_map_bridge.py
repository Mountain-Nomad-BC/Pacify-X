"""Adapter from PX project-map/Atlas retrieval into normalized semantic evidence."""
from __future__ import annotations

import math
from pathlib import Path

from .project_map_retrieval import query_project_map
from .semantic_code_types import stable_id
from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import SemanticEvidence


def _resolve_canonical(
    semantic_map: object | None,
    *,
    hit_id: str,
    path: str,
    include_history: bool,
) -> tuple[str | None, str, tuple[str, ...]]:
    """Resolve a project-map hit to canonical identity through the resolver.

    Returns ``(canonical_entity_id, status, candidates)``. The status is
    ``resolved``, ``ambiguous`` or ``unresolved``. A raw projection ID or a
    filesystem path is never treated as identity: resolution must come from the
    canonical owner, and ambiguity is reported rather than resolved by picking
    a winner.
    """
    if semantic_map is None:
        return None, "not_attempted", ()
    resolver = getattr(semantic_map, "resolve_reference", None)
    dual = getattr(semantic_map, "resolve_any", None)
    candidates: list[str] = []
    for reference in (hit_id, path):
        if not reference:
            continue
        try:
            found = resolver(reference, include_history=include_history)
        except Exception:
            # A reference the current policy refuses is simply unresolved; it
            # must never abort retrieval or be treated as an owner.
            continue
        for entity in found or ():
            identifier = getattr(entity, "canonical_entity_id", None)
            if identifier is None:
                intrinsic_id = getattr(entity, "entity_id", None)
                if isinstance(intrinsic_id, str) and intrinsic_id.startswith("pxe1:"):
                    identifier = intrinsic_id
            if identifier and identifier not in candidates:
                candidates.append(identifier)
    if not candidates:
        try:
            dual_result = dual("file", path, include_history=include_history) if callable(dual) and path else None
        except Exception:
            dual_result = None
        if isinstance(dual_result, dict) and dual_result.get("resolved_as") in {"current", "historical"}:
            candidates.extend(item for item in dual_result.get("entity_ids", ()) if isinstance(item, str) and item.startswith("pxe1:"))
    if len(candidates) == 1:
        return candidates[0], "resolved", tuple(candidates)
    if len(candidates) > 1:
        return None, "ambiguous", tuple(candidates)
    return None, "unresolved", ()


def query_project_map_evidence(
    project_id: str,
    root: Path,
    query: str,
    *,
    top_k: int = 10,
    limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
    semantic_map: object | None = None,
    include_history: bool = False,
) -> tuple[dict[str, object], tuple[SemanticEvidence, ...]]:
    if type(query) is not str or not query.strip() or len(query.encode("utf-8")) > limits.max_query_bytes:
        raise ValueError("query must be nonempty and within budget")
    if type(top_k) is not int or not 1 <= top_k <= limits.max_results:
        raise ValueError("top_k must be a positive integer within result budget")
    if type(include_history) is not bool:
        raise ValueError("include_history must be an explicit boolean")
    max_result_bytes = min(limits.max_context_bytes * 4, 1024 * 1024)
    result = query_project_map(
        Path(root),
        query,
        top_k=top_k,
        max_result_bytes=max_result_bytes,
    )
    if not isinstance(result, dict):
        raise ValueError("project-map query result must be an object")
    revision = str(result.get("map_revision") or "") or None
    raw_hits = result.get("hits") or ()
    if not isinstance(raw_hits, (list, tuple)):
        raise ValueError("project-map hits must be a list")

    evidence: list[SemanticEvidence] = []
    for hit in list(raw_hits)[:limits.max_results]:
        if not isinstance(hit, dict):
            raise ValueError("project-map hit must be an object")
        hit_id = hit.get("id")
        if not isinstance(hit_id, str) or not hit_id.strip():
            raise ValueError("project-map hit requires an id")
        source_id = stable_id("atlas", project_id, hit_id, revision)
        path = str(hit.get("path") or "")
        line_start = hit.get("line_start")
        line_end = hit.get("line_end")
        locator = path
        if line_start:
            locator += f"#L{line_start}"
            if line_end and line_end != line_start:
                locator += f"-L{line_end}"
        text = " ".join(
            str(value)
            for value in (hit.get("title"), hit.get("summary"))
            if value
        )
        raw_score = hit.get("score") or 0.0
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            raise ValueError("project-map score must be numeric")
        score = float(raw_score)
        if not math.isfinite(score):
            raise ValueError("project-map score must be finite")
        graph_score = max(0.0, min(1.0, score / (score + 1.0))) if score >= 0 else 0.0
        # The evidence source_id stays a versioned evidence identity in its own
        # domain. Canonical identity is attached alongside it, resolved through
        # the canonical owner, so no consumer has to treat the path or the
        # revision as identity.
        canonical_entity_id, resolution_status, resolution_candidates = _resolve_canonical(
            semantic_map, hit_id=hit_id, path=path, include_history=include_history
        )
        evidence.append(
            SemanticEvidence(
                source_id=source_id,
                source_kind="project_map",
                title=str(hit.get("title") or hit_id),
                text=text,
                project_id=project_id,
                lineage="runtime.project_map_retrieval.query_project_map",
                locator=locator or f"project-map:{hit_id}",
                revision=revision,
                trust=1.0,
                graph_score=graph_score,
                metadata={
                    "kind": hit.get("kind"),
                    "rank": hit.get("rank"),
                    "reasons": hit.get("reasons", ()),
                    "canonical_entity_id": canonical_entity_id,
                    "canonical_resolution": resolution_status,
                    "canonical_candidates": list(resolution_candidates),
                },
                structured={"relations": hit.get("relations", ())},
            )
        )
    return result, tuple(evidence)
