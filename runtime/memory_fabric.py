"""Project-scoped, provenance-backed memory primitives and provider assurance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence


TOKEN = re.compile(r"[a-z0-9]+")
NIBBLE_ALPHABET = "ABCDEFGHIJKLMNOP"
MEMORY_TYPES = frozenset({
    "fact", "decision", "failure", "pattern", "preference", "skill", "architecture",
    "risk", "assumption", "lesson", "relationship", "procedure",
})
CERTIFICATION_STATES = ("candidate", "validated", "certified", "trusted", "revoked", "superseded")


def normalize_key(value: str) -> str:
    normalized = " ".join(TOKEN.findall(value.casefold()))
    if not normalized:
        raise ValueError("memory key must contain alphanumeric content")
    return normalized


def _address_digest(key: str) -> str:
    return hashlib.sha256(b"memory-address-v1\0" + normalize_key(key).encode("utf-8")).hexdigest()


def encode_hex_alpha(hex_value: str) -> str:
    if any(char not in "0123456789abcdef" for char in hex_value.casefold()):
        raise ValueError("hex input required")
    return "".join(NIBBLE_ALPHABET[int(char, 16)] for char in hex_value.casefold())


def decode_hex_alpha(value: str) -> str:
    reverse = {char: format(index, "x") for index, char in enumerate(NIBBLE_ALPHABET)}
    try:
        return "".join(reverse[char] for char in value.upper())
    except KeyError as error:
        raise ValueError("invalid alphabetic address") from error


@dataclass(frozen=True, slots=True)
class ShardAddress:
    normalized_key: str
    address_bits: int
    short_address: str
    bucket_path: tuple[str, ...]
    integrity_sha256: str
    collision_expanded: bool


def assign_shard_address(
    key: str,
    content: bytes,
    occupied_keys: Iterable[str] = (),
    *,
    minimum_bits: int = 8,
    step_bits: int = 4,
    bucket_letters: int = 2,
) -> ShardAddress:
    """Select the shortest unique digest prefix; integrity remains independent."""
    if minimum_bits < 4 or minimum_bits > 256 or minimum_bits % 4:
        raise ValueError("minimum_bits must be a multiple of four between 4 and 256")
    if step_bits < 4 or step_bits % 4 or bucket_letters < 1:
        raise ValueError("step_bits and bucket_letters must be positive nibble-aligned values")
    normalized = normalize_key(key)
    digest = _address_digest(normalized)
    other_digests = {
        _address_digest(other) for other in occupied_keys if normalize_key(other) != normalized
    }
    bits = minimum_bits
    while bits <= 256:
        chars = math.ceil(bits / 4)
        prefix = digest[:chars]
        if not any(other[:chars] == prefix for other in other_digests):
            break
        bits += step_bits
    if bits > 256:
        raise ValueError("address namespace cannot resolve a full-digest collision")
    alpha = encode_hex_alpha(digest[: bits // 4])
    buckets = tuple(alpha[index:index + bucket_letters] for index in range(0, len(alpha), bucket_letters))
    return ShardAddress(
        normalized, bits, alpha, buckets, hashlib.sha256(content).hexdigest(), bits > minimum_bits,
    )


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    workspace_id: str
    project_id: str
    owner_id: str
    session_id: str
    lease_id: str
    title: str
    memory_type: str
    summary: str
    source_artifact: str
    source_sha256: str
    evidence_locator: str
    epistemic_status: str
    confidence: float
    confidence_method: str
    classification: str
    acl: tuple[str, ...]
    observed_at: datetime
    effective_at: datetime
    expires_at: datetime | None = None
    supersedes: tuple[str, ...] = ()
    relationships: tuple[str, ...] = ()
    revision: int = 1
    certification_status: str = "candidate"
    retrieval_enabled: bool = False

    def validation_errors(self) -> tuple[str, ...]:
        errors = []
        mandatory = {
            "memory_id": self.memory_id, "workspace_id": self.workspace_id,
            "project_id": self.project_id, "owner_id": self.owner_id,
            "session_id": self.session_id, "lease_id": self.lease_id,
            "title": self.title, "summary": self.summary,
            "source_artifact": self.source_artifact, "source_sha256": self.source_sha256,
            "evidence_locator": self.evidence_locator, "confidence_method": self.confidence_method,
            "classification": self.classification,
        }
        errors.extend(f"missing_{name}" for name, value in mandatory.items() if not str(value).strip())
        if self.memory_type not in MEMORY_TYPES:
            errors.append("invalid_memory_type")
        if self.epistemic_status not in {"observation", "inference", "proposal"}:
            errors.append("invalid_epistemic_status")
        if not 0.0 <= self.confidence <= 1.0:
            errors.append("confidence_out_of_range")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256.casefold()):
            errors.append("invalid_source_sha256")
        if not self.acl:
            errors.append("acl_missing")
        if self.revision < 1:
            errors.append("invalid_revision")
        if self.certification_status not in CERTIFICATION_STATES:
            errors.append("invalid_certification_status")
        if self.retrieval_enabled and self.certification_status not in {"certified", "trusted"}:
            errors.append("uncertified_retrieval_enabled")
        if self.expires_at and self.expires_at <= self.effective_at:
            errors.append("expiry_not_after_effective")
        return tuple(sorted(set(errors)))


@dataclass(frozen=True, slots=True)
class MemoryDecision:
    decision: str
    reasons: tuple[str, ...]
    record_id: str
    derived_invalidation: tuple[str, ...] = ()


def admit_memory(record: MemoryRecord, *, active_project_id: str, actor_id: str) -> MemoryDecision:
    reasons = list(record.validation_errors())
    if record.project_id != active_project_id:
        reasons.append("foreign_project_memory")
    if record.owner_id != actor_id:
        reasons.append("actor_attribution_mismatch")
    if record.epistemic_status == "proposal" and record.confidence >= 1.0:
        reasons.append("proposal_cannot_be_certain")
    return MemoryDecision("candidate" if not reasons else "quarantine", tuple(sorted(set(reasons))), record.memory_id)


def correction_plan(previous: MemoryRecord, correction: MemoryRecord) -> MemoryDecision:
    reasons = list(correction.validation_errors())
    if previous.certification_status in {"revoked", "superseded"}:
        reasons.append(f"correction_target_{previous.certification_status}")
    if previous.memory_id not in correction.supersedes:
        reasons.append("supersession_link_missing")
    if previous.project_id != correction.project_id:
        reasons.append("cross_project_correction")
    if correction.revision <= previous.revision:
        reasons.append("revision_not_monotonic")
    derived = ("embedding", "graph", "retrieval_cache", "summary", "transfer_exports")
    return MemoryDecision("rebuild_required" if not reasons else "deny", tuple(sorted(set(reasons))), correction.memory_id, derived)


def simhash64(text: str) -> int:
    terms = TOKEN.findall(text.casefold())
    if not terms:
        return 0
    vector = [0] * 64
    for term in terms:
        value = int.from_bytes(hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            vector[bit] += 1 if value & (1 << bit) else -1
    result = 0
    for bit, weight in enumerate(vector):
        if weight >= 0:
            result |= 1 << bit
    return result


def candidate_memories(
    query: str,
    records: Iterable[MemoryRecord],
    *,
    project_id: str,
    actor_id: str,
    max_hamming: int = 18,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Generate project/ACL/lifecycle-scoped candidates; semantic reranking is external."""
    query_hash = simhash64(query)
    current = now or datetime.now(timezone.utc)
    values = tuple(records)
    superseded = {memory_id for record in values for memory_id in record.supersedes}
    candidates = []
    for record in values:
        allowed = actor_id in record.acl or project_id in record.acl
        expired = record.expires_at is not None and record.expires_at <= current
        if (
            record.project_id != project_id
            or record.validation_errors()
            or not allowed
            or expired
            or record.memory_id in superseded
            or record.certification_status not in {"certified", "trusted"}
            or not record.retrieval_enabled
        ):
            continue
        distance = (query_hash ^ simhash64(record.title + " " + record.summary)).bit_count()
        if distance <= max_hamming:
            candidates.append((distance, record.memory_id))
    return tuple(memory_id for _, memory_id in sorted(candidates))


def memory_record_from_mapping(value: Mapping[str, object]) -> MemoryRecord:
    """Create the runtime record from canonical schema/template metadata."""
    required_times = {name: datetime.fromisoformat(str(value[name])) for name in ("observed_at", "effective_at")}
    expires = value.get("expires_at")
    return MemoryRecord(
        memory_id=str(value["memory_id"]), workspace_id=str(value["workspace_id"]),
        project_id=str(value["project_id"]), owner_id=str(value["owner_id"]),
        session_id=str(value["session_id"]), lease_id=str(value["lease_id"]),
        title=str(value["title"]), memory_type=str(value["memory_type"]), summary=str(value["summary"]),
        source_artifact=str(value["source_artifact"]), source_sha256=str(value["source_sha256"]),
        evidence_locator=str(value["evidence_locator"]), epistemic_status=str(value["epistemic_status"]),
        confidence=float(value["confidence"]), confidence_method=str(value["confidence_method"]),
        classification=str(value["classification"]), acl=tuple(map(str, value.get("acl", ()))),
        observed_at=required_times["observed_at"], effective_at=required_times["effective_at"],
        expires_at=datetime.fromisoformat(str(expires)) if expires else None,
        supersedes=tuple(map(str, value.get("supersedes", ()))),
        relationships=tuple(map(str, value.get("relationships", ()))), revision=int(value.get("revision", 1)),
        certification_status=str(value.get("certification_status", "candidate")),
        retrieval_enabled=value.get("retrieval_enabled") is True,
    )


@dataclass(frozen=True, slots=True)
class ProviderIsolationConfig:
    project_id: str
    root: Path
    database_namespace: str
    index_namespace: str
    process_namespace: str
    shared_process: bool
    source_of_truth: bool = False


@dataclass(frozen=True, slots=True)
class ProviderIsolationEvidence:
    foreign_read_denied: bool
    foreign_write_denied: bool
    foreign_prompt_log_denied: bool
    global_slot_isolated: bool
    attribution_preserved: bool
    backend_errors_propagated: bool
    correction_non_retrieval_proved: bool


def certify_provider_isolation(
    config: ProviderIsolationConfig,
    evidence: ProviderIsolationEvidence,
    *,
    project_root: Path,
) -> MemoryDecision:
    reasons = ["self_attested_provider_evidence_is_not_certifying"]
    resolved = config.root.resolve()
    expected = project_root.resolve()
    try:
        resolved.relative_to(expected)
    except ValueError:
        reasons.append("provider_root_outside_project_scope")
    if config.shared_process:
        reasons.append("shared_provider_process_forbidden")
    if config.source_of_truth:
        reasons.append("external_provider_cannot_be_source_of_truth")
    if not config.project_id or not config.database_namespace or not config.index_namespace or not config.process_namespace:
        reasons.append("provider_namespace_incomplete")
    for name, passed in asdict(evidence).items():
        if not passed:
            reasons.append(f"isolation_test_failed:{name}")
    return MemoryDecision("disabled", tuple(sorted(reasons)), config.project_id)


@dataclass(frozen=True, slots=True)
class BackendResult:
    status: str
    items: tuple[object, ...]
    error_code: str | None = None


def normalize_backend_result(*, items: Sequence[object] | None = None, error: Exception | None = None) -> BackendResult:
    """Never collapse a backend failure into a truthful-looking empty result."""
    if error is not None:
        return BackendResult("error", (), type(error).__name__)
    values = tuple(items or ())
    return BackendResult("ok" if values else "empty", values)


@dataclass(frozen=True, slots=True)
class MaintenancePlan:
    actions: tuple[Mapping[str, object], ...]
    dry_run: bool
    human_approval_required: bool
    hard_delete_allowed: bool = False


def plan_self_healing(findings: Iterable[Mapping[str, object]]) -> MaintenancePlan:
    actions = []
    for finding in findings:
        kind = str(finding.get("kind", "unknown"))
        if kind in {"duplicate", "stale", "broken_link", "orphan_index", "invalid_hash"}:
            actions.append({
                "kind": kind, "target": str(finding.get("target", "")),
                "action": "quarantine_and_rebuild" if kind in {"orphan_index", "invalid_hash"} else "propose_repair",
                "source_remains_canonical": True,
            })
    return MaintenancePlan(tuple(actions), dry_run=True, human_approval_required=True)
