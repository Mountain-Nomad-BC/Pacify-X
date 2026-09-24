"""Adapter from PX project-map/Atlas retrieval into normalized semantic evidence."""
from __future__ import annotations

import math
from pathlib import Path

from .project_map_retrieval import query_project_map
from .semantic_code_types import stable_id
from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import SemanticEvidence


def query_project_map_evidence(
    project_id: str,
    root: Path,
    query: str,
    *,
    top_k: int = 10,
    limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
) -> tuple[dict[str, object], tuple[SemanticEvidence, ...]]:
    if type(query) is not str or not query.strip() or len(query.encode("utf-8")) > limits.max_query_bytes:
        raise ValueError("query must be nonempty and within budget")
    if type(top_k) is not int or not 1 <= top_k <= limits.max_results:
        raise ValueError("top_k must be a positive integer within result budget")
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
                },
                structured={"relations": hit.get("relations", ())},
            )
        )
    return result, tuple(evidence)
