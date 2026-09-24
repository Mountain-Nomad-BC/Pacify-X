"""Bounded category-aware cognitive query over the existing PX cognitive map.

This module is a subordinate query adapter. It does not own canonical records,
retrieval generations, lifecycle admission, model routing, or hydration effects.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .cognitive_core.navigator import CognitiveNavigator
from .tiny_model_operator import OperatorCandidate, TinyModelOperator
from .context_checkpoint import PressurePolicy, pressure_action

CORE_CATEGORIES = (
    "subjects", "knowledge", "goals", "actions",
    "skills", "operations", "workflows", "orchestrations",
)
_RETRIEVABLE_STATUS = frozenset({"active", "admitted", "certified", "trusted", "executable", "reference", "reference_only", "formula"})
_KIND_CATEGORY = {
    "knowledge": "knowledge",
    "formula": "knowledge",
    "skill": "skills",
    "capability": "operations",
    "script": "actions",
}


def _stable(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _bounded(value: object, maximum: int) -> str:
    text = str(value or "").strip()
    if len(text.encode("utf-8")) > maximum:
        raise ValueError("text exceeds cognitive-query bound")
    return text


@dataclass(frozen=True, slots=True)
class CognitiveCandidate:
    category: str
    object_id: str
    revision: str
    score: float
    summary: str
    lifecycle: str
    project_id: str = ""
    evidence_refs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    hydrate_ref: str | None = None
    source_key: str | None = None

    def validate(self) -> None:
        if self.category not in CORE_CATEGORIES:
            raise ValueError(f"unsupported cognitive category: {self.category}")
        if not self.object_id or not self.revision:
            raise ValueError("candidate identity/revision required")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("candidate score must be in [0,1]")
        _bounded(self.summary, 4096)
        if len(self.evidence_refs) > 16 or len(self.reasons) > 16:
            raise ValueError("candidate evidence/reason bound exceeded")


@dataclass(frozen=True, slots=True)
class CognitiveQueryResult:
    query_id: str
    project_id: str
    generation_id: str
    top_per_category: int
    categories: Mapping[str, tuple[CognitiveCandidate, ...]]
    librarian_receipts: tuple[str, ...]
    trace: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "px.cognitive-query-result/1.0",
            "query_id": self.query_id,
            "project_id": self.project_id,
            "generation_id": self.generation_id,
            "top_per_category": self.top_per_category,
            "categories": {key: [asdict(item) for item in self.categories.get(key, ())] for key in CORE_CATEGORIES},
            "librarian_receipts": list(self.librarian_receipts),
            "trace": list(self.trace),
            "authority_granted": False,
        }


def _category_for_record(record: Mapping[str, Any]) -> str | None:
    kind = str(record.get("kind", ""))
    if kind == "workflow":
        domain = str(record.get("domain", "")).casefold()
        return "orchestrations" if "orchestration" in domain else "workflows"
    return _KIND_CATEGORY.get(kind)


def candidates_from_cognitive_index(
    payload: Mapping[str, Any], query: str, *, project_id: str = "", limit: int = 96
) -> tuple[CognitiveCandidate, ...]:
    """Search existing cognitive-map metadata and normalize it into closed candidates."""
    navigator = CognitiveNavigator(payload)
    result = navigator.search(query, limit=max(1, min(int(limit), 192)), graph_depth=1)
    by_key = {str(item.get("key")): item for item in payload.get("records", ()) if isinstance(item, Mapping)}
    maximum = max((hit.score for hit in result.hits), default=1.0)
    rows: list[CognitiveCandidate] = []
    for hit in result.hits:
        record = by_key.get(hit.key, {})
        category = _category_for_record(record)
        if category is None or hit.status not in _RETRIEVABLE_STATUS:
            continue
        score = min(1.0, max(0.0, hit.score / maximum if maximum > 0 else 0.0))
        evidence = tuple(
            str(item.get("path")) for item in record.get("source_provenance", ())
            if isinstance(item, Mapping) and item.get("path")
        )[:16]
        rows.append(CognitiveCandidate(
            category=category,
            object_id=hit.identifier,
            revision=str(record.get("source_sha256") or payload.get("revision") or "unknown"),
            score=score,
            summary=_bounded(record.get("summary") or record.get("title") or hit.identifier, 4096),
            lifecycle=hit.status,
            project_id=project_id,
            evidence_refs=evidence,
            reasons=tuple(hit.reasons[:16]),
            hydrate_ref=hit.path or hit.implementation_path or None,
            source_key=hit.key,
        ))
    return tuple(rows)


def bounded_topk(
    candidates: Iterable[CognitiveCandidate], *, project_id: str, top_per_category: int = 3
) -> dict[str, list[CognitiveCandidate]]:
    if not 1 <= int(top_per_category) <= 3:
        raise ValueError("top_per_category must be 1..3")
    buckets: dict[str, dict[tuple[str, str], CognitiveCandidate]] = {key: {} for key in CORE_CATEGORIES}
    for item in candidates:
        item.validate()
        if item.lifecycle not in _RETRIEVABLE_STATUS:
            continue
        if item.project_id and project_id and item.project_id != project_id:
            continue
        key = (item.object_id, item.revision)
        prior = buckets[item.category].get(key)
        if prior is None or (item.score, item.object_id) > (prior.score, prior.object_id):
            buckets[item.category][key] = item
    return {
        category: sorted(rows.values(), key=lambda item: (-item.score, item.object_id, item.revision))[:top_per_category]
        for category, rows in buckets.items()
    }


def _ambiguous(rows: Sequence[CognitiveCandidate], *, margin: float) -> bool:
    if len(rows) < 2:
        return False
    if rows[0].score >= 0.999:
        return False
    return (rows[0].score - rows[1].score) < margin


def cognitive_query(
    query: str,
    *,
    project_id: str,
    generation_id: str,
    candidates: Iterable[CognitiveCandidate],
    top_per_category: int = 3,
    librarian: TinyModelOperator | None = None,
    librarian_margin: float = 0.08,
    retrieval_generation: str = "unknown",
    contract_revision: str = "px.cognitive-query/1.0",
) -> CognitiveQueryResult:
    query = _bounded(query, 16_384)
    if not query:
        raise ValueError("cognitive query must be nonempty")
    if not 0.0 <= float(librarian_margin) <= 1.0:
        raise ValueError("librarian margin must be in [0,1]")
    initial = bounded_topk(candidates, project_id=project_id, top_per_category=3)
    final: dict[str, tuple[CognitiveCandidate, ...]] = {}
    receipts: list[str] = []
    traces: list[str] = []
    for category in CORE_CATEGORIES:
        rows = list(initial[category])
        if librarian is not None and _ambiguous(rows, margin=float(librarian_margin)):
            decision = librarian.select(
                query=query,
                purpose=f"rerank-{category}",
                candidates=tuple(OperatorCandidate(
                    candidate_id=item.object_id,
                    category=item.category,
                    revision=item.revision,
                    summary=item.summary,
                    score=item.score,
                    evidence_refs=item.evidence_refs,
                ) for item in rows),
                contract_revision=contract_revision,
                retrieval_generation=retrieval_generation,
                constraints=("Select only existing candidate IDs.", "Return unresolved when evidence is insufficient."),
            )
            receipts.append(decision.receipt_sha256)
            if not decision.unresolved:
                by_id = {item.object_id: item for item in rows}
                selected = [by_id[item] for item in decision.selected_ids]
                remaining = [item for item in rows if item.object_id not in decision.selected_ids]
                rows = selected + remaining
            traces.append(f"librarian:{category}:{'unresolved' if decision.unresolved else 'reranked'}")
        else:
            traces.append(f"deterministic:{category}:{len(rows)}")
        final[category] = tuple(rows[:top_per_category])
    identity = {
        "query": query,
        "project_id": project_id,
        "generation_id": generation_id,
        "top_per_category": top_per_category,
        "categories": {key: [(item.object_id, item.revision, item.score) for item in final[key]] for key in CORE_CATEGORIES},
        "receipts": receipts,
    }
    return CognitiveQueryResult(
        query_id=f"cq-{_stable(identity)[:24]}",
        project_id=project_id,
        generation_id=generation_id,
        top_per_category=top_per_category,
        categories=final,
        librarian_receipts=tuple(receipts),
        trace=tuple(traces),
    )


def hydrate_selected(
    result: CognitiveQueryResult,
    selections: Mapping[str, Sequence[str]],
    hydrate: Callable[[CognitiveCandidate], Mapping[str, Any]],
    *,
    max_records: int = 8,
    context_used_tokens: int | None = None,
    context_max_tokens: int | None = None,
    checkpoint_publication_receipt: Mapping[str, Any] | None = None,
    pressure_policy: PressurePolicy = PressurePolicy(),
) -> dict[str, object]:
    if not 1 <= int(max_records) <= 24:
        raise ValueError("max_records must be 1..24")
    pressure = "none"
    if context_used_tokens is not None or context_max_tokens is not None:
        if context_used_tokens is None or context_max_tokens is None:
            raise ValueError("both context token counts are required")
        pressure = pressure_action(int(context_used_tokens), int(context_max_tokens), pressure_policy)
        if pressure in {"checkpoint-required-before-bulk-hydration", "hard-checkpoint-and-block-bulk-hydration"}:
            receipt = dict(checkpoint_publication_receipt or {})
            if receipt.get("schema_version") != "px.context-checkpoint-publication/1.0" or receipt.get("compaction_permitted") is not True or not receipt.get("checkpoint_id") or not receipt.get("receipt_sha256"):
                raise RuntimeError(f"context pressure blocks hydration until a published checkpoint exists: {pressure}")
    allowed = {category: {item.object_id: item for item in result.categories.get(category, ())} for category in CORE_CATEGORIES}
    hydrated: list[dict[str, object]] = []
    for category, ids in selections.items():
        if category not in CORE_CATEGORIES:
            raise ValueError(f"unsupported hydration category: {category}")
        for object_id in ids:
            if len(hydrated) >= max_records:
                raise ValueError("hydration budget exceeded")
            item = allowed[category].get(str(object_id))
            if item is None:
                raise ValueError(f"hydration requested non-result ID: {category}:{object_id}")
            body = dict(hydrate(item))
            hydrated.append({"category": category, "id": item.object_id, "revision": item.revision, "body": body})
    return {
        "schema_version": "px.cognitive-hydration/1.0",
        "query_id": result.query_id,
        "generation_id": result.generation_id,
        "records": hydrated,
        "context_pressure": pressure,
        "checkpoint_id": (checkpoint_publication_receipt or {}).get("checkpoint_id") if pressure != "none" else None,
        "authority_granted": False,
    }


def query_repository_index(
    source_root: Path,
    query: str,
    *,
    project_id: str = "",
    generation_id: str | None = None,
    top_per_category: int = 3,
) -> CognitiveQueryResult:
    path = Path(source_root) / "registry" / "cognitive_map_index.json"
    raw = path.read_bytes()
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("cognitive map exceeds bounded input")
    payload = json.loads(raw)
    if not isinstance(payload, Mapping):
        raise ValueError("cognitive map must be a JSON object")
    candidates = candidates_from_cognitive_index(payload, query, project_id=project_id)
    generation = generation_id or str(payload.get("revision") or hashlib.sha256(raw).hexdigest())
    return cognitive_query(
        query,
        project_id=project_id,
        generation_id=generation,
        candidates=candidates,
        top_per_category=top_per_category,
    )
