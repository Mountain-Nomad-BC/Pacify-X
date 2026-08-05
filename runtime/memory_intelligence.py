"""Layered, scoped memory lifecycle operations over the canonical memory vault.

This module adds capture, conflict, promotion, ranking, loadout, context assembly,
scene, offload, durability, and evaluation behavior without introducing another
memory store. ``MemoryRecord`` and ``MemoryVault`` remain the canonical owners.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Callable, Iterable, Mapping, Sequence, TypeVar

from .memory_fabric import MemoryRecord


WORD = re.compile(r"[a-z0-9_./-]+")
HIGH_IMPACT_TYPES = frozenset(
    {
        "instruction",
        "constraint",
        "project_doctrine",
        "team_model",
        "user_core",
        "agent_profile",
    }
)
WRAPPERS = (
    re.compile(r"<system[-_ ]?reminder>.*?</system[-_ ]?reminder>", re.I | re.S),
    re.compile(r"<additional_data>.*?</additional_data>", re.I | re.S),
    re.compile(r"<current_time>.*?</current_time>", re.I | re.S),
    re.compile(r"<opened_files?>.*?</opened_files?>", re.I | re.S),
)
SECRETS = (
    (
        "named_secret",
        re.compile(
            r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{12,}"
        ),
    ),
    ("api_token", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
INJECTIONS = (
    (
        "instruction_override",
        re.compile(r"(?i)ignore (?:all|any|the) previous instructions"),
    ),
    (
        "prompt_exfiltration",
        re.compile(r"(?i)reveal (?:the )?(?:system|developer) prompt"),
    ),
    (
        "forced_trust",
        re.compile(r"(?i)store this as (?:a )?(?:permanent|trusted) memory"),
    ),
)
T = TypeVar("T")


def _terms(value: str) -> set[str]:
    return set(WORD.findall(value.casefold()))


def _stable(value: object) -> str:
    rendered = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _write_new(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


@dataclass(frozen=True, slots=True)
class CaptureResult:
    original_sha256: str
    sanitized_sha256: str
    sanitized: str
    removed_fragments: int
    secret_finding_codes: tuple[str, ...]
    injection_finding_codes: tuple[str, ...]
    admission: str


def sanitize_capture(text: str) -> CaptureResult:
    """Remove harness noise and redact secrets without echoing secret values."""
    if not isinstance(text, str):
        raise TypeError("capture text must be a string")
    original = text
    removed = 0
    for pattern in WRAPPERS:
        text, count = pattern.subn("", text)
        removed += count
    text, count = re.subn(r"(?ms)^\s*Tool (?:call|result):.*?(?=\n\S|\Z)", "", text)
    removed += count
    secret_codes = tuple(
        sorted({code for code, pattern in SECRETS if pattern.search(text)})
    )
    injection_codes = tuple(
        sorted({code for code, pattern in INJECTIONS if pattern.search(text)})
    )
    for _, pattern in SECRETS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    admission = (
        "rejected"
        if not text
        else ("quarantined" if secret_codes or injection_codes else "accepted")
    )
    return CaptureResult(
        hashlib.sha256(original.encode("utf-8")).hexdigest(),
        hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text,
        removed,
        secret_codes,
        injection_codes,
        admission,
    )


def capture_event(
    root: Path,
    *,
    project_id: str,
    source_kind: str,
    source_locator: str,
    content: str,
    scope: Mapping[str, str] | None = None,
    apply: bool = False,
) -> dict[str, object]:
    """Plan or append one immutable L0 evidence event to the canonical control tree."""
    if not project_id or not source_locator:
        raise ValueError("project and source locator are required")
    if source_kind not in {
        "conversation",
        "tool_result",
        "document",
        "code",
        "workflow",
        "human_review",
        "external_import",
    }:
        raise ValueError("unsupported memory source kind")
    capture = sanitize_capture(content)
    resolved_scope = {"project_id": project_id, **dict(scope or {})}
    if resolved_scope["project_id"] != project_id:
        raise ValueError("capture scope crosses project boundary")
    event_id = (
        "mev_"
        + _stable(
            {
                "project_id": project_id,
                "source_kind": source_kind,
                "source_locator": source_locator,
                "original_sha256": capture.original_sha256,
            }
        )[:24]
    )
    payload = {
        "schema_version": "1.0",
        "event_id": event_id,
        "project_id": project_id,
        "scope": resolved_scope,
        "source": {"kind": source_kind, "locator": source_locator},
        "content_hash": capture.sanitized_sha256,
        "original_content_hash": capture.original_sha256,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "content": capture.sanitized,
        "sanitization": {
            "removed_fragments": capture.removed_fragments,
            "secret_finding_codes": list(capture.secret_finding_codes),
            "injection_finding_codes": list(capture.injection_finding_codes),
        },
        "admission_status": capture.admission,
    }
    relative = Path(".memory-control") / "evidence" / f"{event_id}.json"
    target = root.resolve() / relative
    if apply:
        rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            comparable = {
                key: value for key, value in existing.items() if key != "captured_at"
            }
            planned = {
                key: value for key, value in payload.items() if key != "captured_at"
            }
            if comparable != planned:
                raise ValueError("capture event identity collision or drift")
        else:
            _write_new(target, rendered)
    return {
        "valid": True,
        "apply": apply,
        "path": relative.as_posix(),
        "event": payload,
    }


@dataclass(frozen=True, slots=True)
class ConflictDecision:
    action: str
    target_ids: tuple[str, ...]
    confidence: float
    reasons: tuple[str, ...]


def classify_conflict(
    candidate: MemoryRecord, existing: Iterable[MemoryRecord]
) -> ConflictDecision:
    """Classify similarity within one project; never infer a cross-project conflict."""
    scoped = tuple(
        item
        for item in existing
        if item.project_id == candidate.project_id
        and item.memory_id != candidate.memory_id
    )
    candidate_terms = _terms(candidate.title + " " + candidate.summary)
    scored = []
    for item in scoped:
        item_terms = _terms(item.title + " " + item.summary)
        union = candidate_terms | item_terms
        scored.append(
            (len(candidate_terms & item_terms) / len(union) if union else 0.0, item)
        )
    scored.sort(key=lambda item: (-item[0], item[1].memory_id))
    if not scored or scored[0][0] < 0.18:
        return ConflictDecision(
            "independent", (), 0.75, ("no close project-scoped memory",)
        )
    similarity, best = scored[0]
    negative = {
        "not",
        "never",
        "avoid",
        "forbidden",
        "deprecated",
        "replaced",
        "instead",
    }
    opposing = bool(candidate_terms & negative) != bool(_terms(best.summary) & negative)
    if similarity >= 0.90:
        action, reason = "duplicate", "near-identical scoped content"
    elif similarity >= 0.55 and opposing:
        action, reason = "contradiction", "similar subject with opposing polarity"
    elif similarity >= 0.55 and len(candidate.summary) > len(best.summary) * 1.15:
        action, reason = "enrichment", "candidate adds material detail"
    elif similarity >= 0.45:
        action, reason = (
            "possible_supersession",
            "same subject requires temporal review",
        )
    else:
        action, reason = "related", "related but not merge-safe"
    return ConflictDecision(action, (best.memory_id,), round(similarity, 6), (reason,))


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    decision: str
    target_status: str
    required_reviews: int
    evidence_count: int
    reasons: tuple[str, ...]


def decide_promotion(
    candidate: MemoryRecord,
    *,
    independent_evidence_ids: Iterable[str],
    reviewer_ids: Iterable[str] = (),
    conflict: ConflictDecision | None = None,
    minimum_confidence: float = 0.75,
) -> PromotionDecision:
    evidence = tuple(sorted(set(filter(None, map(str, independent_evidence_ids)))))
    reviewers = tuple(sorted(set(filter(None, map(str, reviewer_ids)))))
    if candidate.certification_status == "quarantined":
        return PromotionDecision(
            "quarantine",
            "quarantined",
            1,
            len(evidence),
            ("candidate failed admission",),
        )
    if conflict and conflict.action == "duplicate":
        return PromotionDecision(
            "skip", "candidate", 0, len(evidence), ("duplicate memory",)
        )
    if conflict and conflict.action == "contradiction":
        return PromotionDecision(
            "dispute",
            "disputed",
            1,
            len(evidence),
            ("credible contradiction requires resolution",),
        )
    reasons = []
    high_impact = candidate.memory_type in HIGH_IMPACT_TYPES
    if candidate.confidence < minimum_confidence:
        reasons.append("confidence below promotion threshold")
    if not evidence:
        reasons.append("independent evidence is required")
    if high_impact and len(evidence) < 2:
        reasons.append("high-impact memory requires two independent evidence sources")
    if high_impact and not reviewers:
        reasons.append("high-impact memory requires explicit human review")
    if candidate.epistemic_status == "inference" and not reviewers:
        reasons.append("inferred memory requires review")
    if reasons:
        return PromotionDecision(
            "hold", "candidate", 1 if high_impact else 0, len(evidence), tuple(reasons)
        )
    return PromotionDecision(
        "promote",
        "validated",
        1 if high_impact else 0,
        len(evidence),
        ("promotion gates satisfied",),
    )


@dataclass(frozen=True, slots=True)
class MemoryCaller:
    project_id: str
    actor_id: str
    agent_id: str
    team_id: str | None = None
    user_id: str | None = None
    task_id: str | None = None


def can_access(caller: MemoryCaller, record: MemoryRecord) -> bool:
    if caller.project_id != record.project_id:
        return False
    explicit = (
        caller.actor_id in record.acl
        or caller.project_id in record.acl
        or caller.agent_id in record.fixed_agent_ids
    )
    if record.visibility == "project":
        return explicit
    if record.visibility == "private":
        return bool(caller.user_id and caller.user_id == record.user_id and explicit)
    if record.visibility == "team":
        return bool(caller.team_id and caller.team_id == record.team_id and explicit)
    if record.visibility == "agent":
        return (
            caller.agent_id == record.agent_id
            or caller.agent_id in record.fixed_agent_ids
        )
    return explicit and caller.actor_id in record.acl


@dataclass(frozen=True, slots=True)
class LoadoutBinding:
    memory_id: str
    mode: str
    priority: int
    borrowed_from_agent_id: str | None = None


def resolve_loadout(
    caller: MemoryCaller,
    records: Iterable[MemoryRecord],
    *,
    max_assets: int = 40,
    max_borrowed_agents: int = 2,
) -> tuple[LoadoutBinding, ...]:
    if max_assets < 1 or not 0 <= max_borrowed_agents <= 8:
        raise ValueError("loadout bounds are invalid")
    result = []
    borrowed: set[str] = set()
    ordered = sorted(
        records,
        key=lambda item: (
            caller.agent_id not in item.fixed_agent_ids,
            -item.priority,
            item.memory_id,
        ),
    )
    for record in ordered:
        if not can_access(caller, record) or record.certification_status not in {
            "certified",
            "trusted",
        }:
            continue
        source_agent = record.agent_id
        borrowed_from = None
        if source_agent and source_agent != caller.agent_id:
            if source_agent not in borrowed and len(borrowed) >= max_borrowed_agents:
                continue
            borrowed.add(source_agent)
            borrowed_from = source_agent
        mode = (
            "fixed"
            if caller.agent_id in record.fixed_agent_ids
            else (
                "index_only"
                if record.layer == "L2"
                else ("evidence_only" if record.layer == "L0" else "query")
            )
        )
        result.append(
            LoadoutBinding(record.memory_id, mode, record.priority, borrowed_from)
        )
        if len(result) >= max_assets:
            break
    return tuple(result)


@dataclass(frozen=True, slots=True)
class RankedMemory:
    record: MemoryRecord
    score: float
    components: Mapping[str, float]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecallResult:
    selected: tuple[RankedMemory, ...]
    rejected: tuple[Mapping[str, str], ...]


def _rrf(lists: Sequence[Sequence[str]], *, constant: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for values in lists:
        for rank, memory_id in enumerate(values, start=1):
            scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (constant + rank)
    return scores


def rank_memories(
    query: str,
    records: Iterable[MemoryRecord],
    *,
    caller: MemoryCaller,
    max_items: int = 12,
    semantic_scores: Mapping[str, float] | None = None,
    graph_scores: Mapping[str, float] | None = None,
    forbidden_ids: Iterable[str] = (),
    now: datetime | None = None,
) -> RecallResult:
    if not query.strip() or max_items < 1:
        raise ValueError("query and positive item budget are required")
    semantic_scores = semantic_scores or {}
    graph_scores = graph_scores or {}
    forbidden = set(map(str, forbidden_ids))
    current = now or datetime.now(timezone.utc)
    query_terms = _terms(query)
    eligible: list[MemoryRecord] = []
    rejected: list[dict[str, str]] = []
    for record in records:
        reason = None
        if record.memory_id in forbidden:
            reason = "forbidden_id"
        elif not can_access(caller, record):
            reason = "scope_or_acl_denied"
        elif (
            record.certification_status not in {"certified", "trusted"}
            or not record.retrieval_enabled
        ):
            reason = "not_retrievable"
        elif record.expires_at and record.expires_at <= current:
            reason = "expired"
        elif any(_terms(pattern) <= query_terms for pattern in record.negative_matches):
            reason = "negative_match"
        if reason:
            rejected.append({"memory_id": record.memory_id, "reason": reason})
        else:
            eligible.append(record)
    lexical = sorted(
        (
            item
            for item in eligible
            if query_terms & _terms(item.title + " " + item.summary)
        ),
        key=lambda item: (
            -len(query_terms & _terms(item.title + " " + item.summary)),
            item.memory_id,
        ),
    )
    semantic = sorted(
        (
            item
            for item in eligible
            if float(semantic_scores.get(item.memory_id, 0.0)) > 0.0
        ),
        key=lambda item: (
            -float(semantic_scores.get(item.memory_id, 0.0)),
            item.memory_id,
        ),
    )
    graph = sorted(
        (
            item
            for item in eligible
            if float(graph_scores.get(item.memory_id, 0.0)) > 0.0
        ),
        key=lambda item: (
            -float(graph_scores.get(item.memory_id, 0.0)),
            item.memory_id,
        ),
    )
    bound = sorted(
        (item for item in eligible if caller.agent_id in item.fixed_agent_ids),
        key=lambda item: item.memory_id,
    )
    fused = _rrf(
        tuple(
            tuple(item.memory_id for item in values)
            for values in (lexical, semantic, graph, bound)
        )
    )
    candidates = set(fused)
    for record in eligible:
        if record.memory_id not in candidates:
            rejected.append(
                {"memory_id": record.memory_id, "reason": "no_candidate_signal"}
            )
    ranked = []
    for record in eligible:
        if record.memory_id not in candidates:
            continue
        terms = _terms(record.title + " " + record.summary)
        union = query_terms | terms
        lexical_score = len(query_terms & terms) / len(union) if union else 0.0
        age_days = max(0.0, (current - record.observed_at).total_seconds() / 86400)
        components = {
            "fusion": min(1.0, fused.get(record.memory_id, 0.0) * 16.0) * 0.20,
            "lexical": lexical_score * 0.20,
            "semantic": max(
                0.0, min(1.0, float(semantic_scores.get(record.memory_id, 0.0)))
            )
            * 0.15,
            "graph": max(0.0, min(1.0, float(graph_scores.get(record.memory_id, 0.0))))
            * 0.10,
            "scope": 0.10,
            "binding": (0.08 if caller.agent_id in record.fixed_agent_ids else 0.0),
            "confidence": record.confidence * 0.07,
            "freshness": math.exp(-age_days / 365.0) * 0.04,
            "usage": record.usage_success_rate * 0.06,
        }
        score = round(sum(components.values()), 8)
        reasons = tuple(
            f"{name}={value:.4f}" for name, value in components.items() if value > 0
        )
        ranked.append(RankedMemory(record, score, components, reasons))
    ranked.sort(
        key=lambda item: (-item.score, -item.record.priority, item.record.memory_id)
    )
    return RecallResult(
        tuple(ranked[:max_items]),
        tuple(sorted(rejected, key=lambda item: item["memory_id"])),
    )


@dataclass(frozen=True, slots=True)
class ContextPackage:
    text: str
    selected_ids: tuple[str, ...]
    dropped_ids: tuple[str, ...]
    used_chars: int
    max_chars: int


def assemble_context(
    ranked: Iterable[RankedMemory], *, max_chars: int = 12000
) -> ContextPackage:
    """Assemble bounded L3/L2/L1 context and L0 pointers, never the whole vault."""
    if max_chars < 100:
        raise ValueError("context budget must be at least 100 characters")
    quotas = {
        "L3": int(max_chars * 0.25),
        "L2": int(max_chars * 0.15),
        "L1": int(max_chars * 0.45),
        "L0": max_chars,
    }
    used = {layer: 0 for layer in quotas}
    blocks: list[str] = []
    selected: list[str] = []
    dropped: list[str] = []
    total = 0
    for hit in ranked:
        record = hit.record
        body = (
            f"evidence pointer: {record.evidence_locator}"
            if record.layer == "L0"
            else (record.summary[:400] if record.layer == "L2" else record.summary)
        )
        block = f"[{record.layer}:{record.memory_type}:{record.memory_id}:score={hit.score:.4f}]\n{body}\n"
        layer_cap = (
            int(max_chars * 0.15) if record.layer == "L0" else quotas[record.layer]
        )
        if (
            used[record.layer] + len(block) > layer_cap
            or total + len(block) > max_chars
        ):
            dropped.append(record.memory_id)
            continue
        blocks.append(block)
        selected.append(record.memory_id)
        used[record.layer] += len(block)
        total += len(block)
    return ContextPackage(
        "\n".join(blocks), tuple(selected), tuple(dropped), total, max_chars
    )


@dataclass(frozen=True, slots=True)
class Scene:
    path: str
    summary: str
    memory_ids: tuple[str, ...]
    tags: tuple[str, ...]


def build_scene_index(records: Iterable[MemoryRecord]) -> tuple[Scene, ...]:
    groups: dict[str, list[MemoryRecord]] = {}
    for record in records:
        if record.layer != "L1":
            continue
        key = record.task_id or record.memory_type
        groups.setdefault(key, []).append(record)
    result = []
    for key in sorted(groups):
        items = sorted(groups[key], key=lambda item: item.memory_id)
        ids = tuple(item.memory_id for item in items)
        digest = hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:10]
        slug = "-".join(WORD.findall(key.casefold()))[:48].strip("-") or "scene"
        summary = "; ".join(item.summary[:120].strip() for item in items[:3])
        tags = tuple(sorted({term for item in items for term in _terms(item.title)}))
        result.append(Scene(f"scenes/{slug}-{digest}.md", summary, ids, tags))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class OffloadPointer:
    pointer_id: str
    project_id: str
    source_message_id: str
    tool_call_id: str
    content_hash: str
    summary: str
    storage_locator: str
    reversible: bool = True


def compact_tool_results(
    root: Path,
    messages: Sequence[Mapping[str, object]],
    *,
    project_id: str,
    max_chars: int = 24000,
    protected_tail: int = 6,
    threshold: int = 2000,
    apply: bool = False,
) -> tuple[tuple[dict[str, object], ...], tuple[OffloadPointer, ...]]:
    """Replace old large tool results with hash-verified project-local pointers."""
    if not project_id or min(max_chars, threshold) < 1 or protected_tail < 0:
        raise ValueError("valid project and compaction bounds are required")
    output = [dict(item) for item in messages]
    total = sum(len(str(item.get("content", ""))) for item in output)
    if total <= max_chars:
        return tuple(output), ()
    pointers = []
    stop = max(0, len(output) - protected_tail)
    for index in range(stop):
        message = output[index]
        if message.get("role") != "tool" and message.get("type") != "tool_result":
            continue
        content = str(message.get("content", ""))
        if len(content) <= threshold:
            continue
        source_id = str(message.get("id", index))
        tool_call_id = str(message.get("tool_call_id", ""))
        if not tool_call_id:
            continue
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        pointer_id = (
            "off_"
            + hashlib.sha256(
                f"{project_id}\0{source_id}\0{digest}".encode()
            ).hexdigest()[:24]
        )
        relative = (
            Path(".memory-control")
            / "offload"
            / "objects"
            / digest[:2]
            / f"{digest}.txt"
        )
        target = root.resolve() / relative
        summary = content[:600] + (
            f"\n...[offloaded {len(content) - 600} chars]" if len(content) > 600 else ""
        )
        pointer = OffloadPointer(
            pointer_id,
            project_id,
            source_id,
            tool_call_id,
            digest,
            summary,
            relative.as_posix(),
        )
        if apply:
            if (
                target.exists()
                and hashlib.sha256(target.read_bytes()).hexdigest() != digest
            ):
                raise ValueError("offload object hash mismatch")
            if not target.exists():
                _write_new(target, content)
            receipt = (
                root.resolve()
                / ".memory-control"
                / "offload"
                / "pointers"
                / f"{pointer_id}.json"
            )
            rendered = json.dumps(asdict(pointer), indent=2) + "\n"
            if receipt.exists() and receipt.read_text(encoding="utf-8") != rendered:
                raise ValueError("offload pointer identity collision or drift")
            if not receipt.exists():
                _write_new(receipt, rendered)
        message["content"] = summary + f"\n[pointer:{pointer_id} sha256:{digest}]"
        message["_offloaded"] = True
        pointers.append(pointer)
        total = sum(len(str(item.get("content", ""))) for item in output)
        if total <= max_chars:
            break
    return tuple(output), tuple(pointers)


def restore_offload(root: Path, pointer: OffloadPointer) -> str:
    path = root.resolve() / pointer.storage_locator
    content = path.read_text(encoding="utf-8")
    if hashlib.sha256(content.encode("utf-8")).hexdigest() != pointer.content_hash:
        raise ValueError("offload restore hash mismatch")
    return content


@dataclass(frozen=True, slots=True)
class WriteReceipt:
    idempotency_key: str
    attempts: int
    status: str
    error_code: str | None


class PersistentWriteQueue:
    """Disk-backed write intents with idempotent retry and explicit degraded state."""

    def __init__(self, root: Path, project_id: str) -> None:
        if not project_id:
            raise ValueError("project ID is required")
        self.root = root.resolve() / ".memory-control" / "write-queue"
        self.project_id = project_id

    def prepare(self, operation: str, payload: Mapping[str, object]) -> str:
        key = hashlib.sha256(
            f"{self.project_id}\0{operation}\0{_stable(payload)}".encode()
        ).hexdigest()
        intent = {
            "schema_version": "1.0",
            "project_id": self.project_id,
            "operation": operation,
            "payload": dict(payload),
            "idempotency_key": key,
        }
        path = self.root / "pending" / f"{key}.json"
        rendered = json.dumps(intent, indent=2, ensure_ascii=False) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != rendered:
            raise ValueError("pending write identity collision")
        if not path.exists() and not (self.root / "completed" / f"{key}.json").exists():
            _write_new(path, rendered)
        return key

    def flush(
        self,
        handler: Callable[[str, Mapping[str, object]], object],
        *,
        attempts: int = 3,
        base_delay: float = 0.01,
    ) -> tuple[WriteReceipt, ...]:
        if attempts < 1 or base_delay < 0:
            raise ValueError("retry policy is invalid")
        pending = (
            tuple(sorted((self.root / "pending").glob("*.json")))
            if (self.root / "pending").is_dir()
            else ()
        )
        receipts = []
        for path in pending:
            intent = json.loads(path.read_text(encoding="utf-8"))
            error_code = None
            status = "failed"
            used = 0
            for index in range(attempts):
                used = index + 1
                try:
                    handler(str(intent["operation"]), dict(intent["payload"]))
                    status = "written"
                    break
                except (
                    Exception
                ) as error:  # backend boundary records code, not secret-bearing text
                    error_code = type(error).__name__
                    if index + 1 < attempts and base_delay:
                        time.sleep(base_delay * (2**index))
            receipt = WriteReceipt(
                str(intent["idempotency_key"]), used, status, error_code
            )
            receipt_dir = self.root / "receipts" / receipt.idempotency_key
            sequence = (
                len(tuple(receipt_dir.glob("*.json"))) + 1
                if receipt_dir.is_dir()
                else 1
            )
            receipt_path = receipt_dir / f"{sequence:06d}-{status}.json"
            _write_new(receipt_path, json.dumps(asdict(receipt), indent=2) + "\n")
            if status == "written":
                completed = self.root / "completed" / path.name
                completed.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, completed)
            receipts.append(receipt)
        return tuple(receipts)

    def health(self) -> dict[str, object]:
        pending = (
            tuple((self.root / "pending").glob("*.json"))
            if (self.root / "pending").is_dir()
            else ()
        )
        failed = []
        if (self.root / "receipts").is_dir():
            for directory in (self.root / "receipts").iterdir():
                paths = (
                    tuple(sorted(directory.glob("*.json")))
                    if directory.is_dir()
                    else ()
                )
                if (
                    paths
                    and json.loads(paths[-1].read_text(encoding="utf-8")).get("status")
                    == "failed"
                ):
                    failed.append(directory.name)
        return {
            "valid": not failed,
            "state": "degraded" if failed else "ready",
            "pending": len(pending),
            "failed_receipts": len(failed),
        }


def evaluate_memory_retrieval(
    fixtures: Iterable[Mapping[str, object]],
    records: Iterable[MemoryRecord],
    *,
    caller: MemoryCaller,
) -> dict[str, object]:
    """Evaluate expected recall, MRR/nDCG, forbidden hits, and traceability."""
    rows = []
    expected_total = found_total = forbidden_hits = 0
    reciprocal_sum = ndcg_sum = 0.0
    records = tuple(records)
    for fixture in fixtures:
        expected = set(map(str, fixture.get("expected_ids", ())))
        forbidden = set(map(str, fixture.get("forbidden_ids", ())))
        result = rank_memories(
            str(fixture["query"]),
            records,
            caller=caller,
            max_items=int(fixture.get("max_results", 5)),
            forbidden_ids=(),
        )
        ids = [item.record.memory_id for item in result.selected]
        found = expected & set(ids)
        bad = forbidden & set(ids)
        ranks = [ids.index(item) + 1 for item in found]
        reciprocal = 1.0 / min(ranks) if ranks else 0.0
        dcg = sum(1.0 / math.log2(rank + 1) for rank in ranks)
        ideal = sum(
            1.0 / math.log2(rank + 1)
            for rank in range(1, min(len(expected), len(ids)) + 1)
        )
        ndcg = dcg / ideal if ideal else (1.0 if not expected else 0.0)
        expected_total += len(expected)
        found_total += len(found)
        forbidden_hits += len(bad)
        reciprocal_sum += reciprocal
        ndcg_sum += ndcg
        rows.append(
            {
                "fixture_id": str(fixture["fixture_id"]),
                "ids": ids,
                "found": sorted(found),
                "forbidden": sorted(bad),
                "mrr": reciprocal,
                "ndcg": ndcg,
            }
        )
    count = len(rows)
    traceable = all(item.source_sha256 and item.evidence_locator for item in records)
    return {
        "valid": forbidden_hits == 0 and found_total == expected_total and traceable,
        "fixture_count": count,
        "recall": found_total / expected_total if expected_total else 1.0,
        "forbidden_hits": forbidden_hits,
        "mrr": reciprocal_sum / count if count else 1.0,
        "ndcg": ndcg_sum / count if count else 1.0,
        "source_traceable": traceable,
        "rows": rows,
    }


def validate_memory_orchestration(root: Path) -> dict[str, object]:
    path = root / "orchestration/workflows/layered-memory-lifecycle.yaml"
    if not path.is_file():
        return {"valid": False, "errors": ["workflow missing"]}
    text = path.read_text(encoding="utf-8")
    required = (
        "sanitize-capture",
        "persist-l0",
        "extract-l1",
        "resolve-conflicts",
        "promote",
        "build-scenes",
        "resolve-loadout",
        "rank",
        "assemble",
        "evaluate",
    )
    missing = [item for item in required if f'"{item}"' not in text]
    return {
        "valid": not missing,
        "errors": [f"missing step: {item}" for item in missing],
        "effects": ["read_local", "write_project_memory"],
    }
