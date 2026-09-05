"""Immutable, revision-bound agent handoff packets and acknowledgments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Mapping


PACKET_SCHEMA = "px.agent-handoff-packet/1.0"
ACK_SCHEMA = "px.agent-handoff-acknowledgment/1.0"
SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("handoff time must include UTC timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class AgentHandoffPacket:
    schema_version: str
    packet_id: str
    project_id: str
    task_plan_id: str
    task_plan_revision: str
    run_id: str
    sender_agent_id: str
    sender_revision: str
    receiver_agent_id: str
    receiver_revision: str
    evidence: tuple[Mapping[str, object], ...]
    hypotheses: tuple[str, ...]
    open_questions: tuple[str, ...]
    authority: tuple[str, ...]
    budgets: Mapping[str, int]
    memory_query_plan_sha256: str
    created_utc: str
    expires_utc: str
    recovery_of: str | None
    packet_sha256: str


@dataclass(frozen=True, slots=True)
class HandoffAcknowledgment:
    schema_version: str
    packet_id: str
    packet_sha256: str
    receiver_agent_id: str
    receiver_revision: str
    decision: str
    reason: str
    acknowledged_utc: str
    acknowledgment_sha256: str


def _packet_payload(packet: AgentHandoffPacket) -> dict[str, object]:
    payload = asdict(packet)
    payload.pop("packet_sha256", None)
    return payload


def create_handoff_packet(
    *,
    project_id: str,
    task_plan_id: str,
    task_plan_revision: str,
    run_id: str,
    sender_agent_id: str,
    sender_revision: str,
    receiver_agent_id: str,
    receiver_revision: str,
    evidence: Iterable[Mapping[str, object]],
    hypotheses: Iterable[str],
    open_questions: Iterable[str],
    authority: Iterable[str],
    sender_authority: Iterable[str],
    budgets: Mapping[str, int],
    memory_query_plan_sha256: str,
    created_utc: str,
    expires_utc: str,
    recovery_of: str | None = None,
) -> AgentHandoffPacket:
    requested = tuple(sorted(set(map(str, authority))))
    if not requested or not set(requested) <= set(map(str, sender_authority)):
        raise PermissionError("handoff authority exceeds sender authority")
    normalized_budgets = {str(key): int(value) for key, value in sorted(budgets.items())}
    if not normalized_budgets or any(value < 1 for value in normalized_budgets.values()):
        raise ValueError("handoff requires positive explicit budgets")
    bound_evidence = tuple(dict(item) for item in evidence)
    if not bound_evidence:
        raise ValueError("handoff requires evidence")
    for item in bound_evidence:
        if (
            not str(item.get("ref", "")).strip()
            or not SHA256.fullmatch(str(item.get("sha256", "")))
            or not str(item.get("revision", "")).strip()
        ):
            raise ValueError("handoff evidence requires ref, hash, and revision")
    for name, revision in (
        ("task_plan_revision", task_plan_revision),
        ("sender_revision", sender_revision),
        ("receiver_revision", receiver_revision),
        ("memory_query_plan_sha256", memory_query_plan_sha256),
    ):
        if not SHA256.fullmatch(revision):
            raise ValueError(f"{name} must be a SHA-256 revision")
    created = _utc(created_utc)
    expires = _utc(expires_utc)
    if expires <= created:
        raise ValueError("handoff expiration must follow creation")
    base = {
        "schema_version": PACKET_SCHEMA,
        "project_id": project_id,
        "task_plan_id": task_plan_id,
        "task_plan_revision": task_plan_revision,
        "run_id": run_id,
        "sender_agent_id": sender_agent_id,
        "sender_revision": sender_revision,
        "receiver_agent_id": receiver_agent_id,
        "receiver_revision": receiver_revision,
        "evidence": bound_evidence,
        "hypotheses": tuple(map(str, hypotheses)),
        "open_questions": tuple(map(str, open_questions)),
        "authority": requested,
        "budgets": normalized_budgets,
        "memory_query_plan_sha256": memory_query_plan_sha256,
        "created_utc": created_utc,
        "expires_utc": expires_utc,
        "recovery_of": recovery_of,
    }
    packet_id = "handoff-" + _digest(base)[:24]
    payload = {"packet_id": packet_id, **base}
    return AgentHandoffPacket(**payload, packet_sha256=_digest(payload))


def validate_handoff_packet(
    packet: AgentHandoffPacket,
    *,
    expected_project_id: str,
    receiver_agent_id: str,
    receiver_revision: str,
    current_evidence_revisions: Mapping[str, object],
    now_utc: str,
) -> dict[str, object]:
    errors: list[str] = []
    if packet.schema_version != PACKET_SCHEMA:
        errors.append("schema_mismatch")
    if packet.packet_sha256 != _digest(_packet_payload(packet)):
        errors.append("packet_hash_mismatch")
    if packet.project_id != expected_project_id:
        errors.append("project_mismatch")
    if packet.receiver_agent_id != receiver_agent_id:
        errors.append("receiver_mismatch")
    if packet.receiver_revision != receiver_revision:
        errors.append("receiver_revision_mismatch")
    if _utc(packet.expires_utc) <= _utc(now_utc):
        errors.append("packet_expired")
    for item in packet.evidence:
        ref = str(item["ref"])
        if str(current_evidence_revisions.get(ref, "")) != str(item["revision"]):
            errors.append(f"stale_evidence:{ref}")
    return {"valid": not errors, "errors": tuple(sorted(set(errors)))}


def acknowledge_handoff(
    packet: AgentHandoffPacket,
    *,
    decision: str,
    reason: str,
    receiver_agent_id: str,
    receiver_revision: str,
    acknowledged_utc: str,
) -> HandoffAcknowledgment:
    normalized = decision.casefold().strip()
    if normalized not in {"accept", "reject"} or not reason.strip():
        raise ValueError("handoff acknowledgment requires accept/reject and reason")
    if (
        receiver_agent_id != packet.receiver_agent_id
        or receiver_revision != packet.receiver_revision
    ):
        raise PermissionError("handoff acknowledgment receiver revision mismatch")
    payload = {
        "schema_version": ACK_SCHEMA,
        "packet_id": packet.packet_id,
        "packet_sha256": packet.packet_sha256,
        "receiver_agent_id": receiver_agent_id,
        "receiver_revision": receiver_revision,
        "decision": normalized,
        "reason": reason,
        "acknowledged_utc": acknowledged_utc,
    }
    return HandoffAcknowledgment(**payload, acknowledgment_sha256=_digest(payload))


def consume_handoff(
    packet: AgentHandoffPacket,
    acknowledgment: HandoffAcknowledgment | None,
    **validation_context: object,
) -> dict[str, object]:
    if acknowledgment is None or acknowledgment.decision != "accept":
        raise PermissionError("handoff cannot be consumed before valid acknowledgment")
    ack_payload = asdict(acknowledgment)
    ack_sha = ack_payload.pop("acknowledgment_sha256")
    if ack_sha != _digest(ack_payload):
        raise PermissionError("handoff acknowledgment hash mismatch")
    if (
        acknowledgment.packet_id != packet.packet_id
        or acknowledgment.packet_sha256 != packet.packet_sha256
    ):
        raise PermissionError("handoff acknowledgment does not bind the packet")
    validation = validate_handoff_packet(packet, **validation_context)
    if not validation["valid"]:
        raise PermissionError("invalid handoff packet: " + ",".join(validation["errors"]))
    return {
        "packet_id": packet.packet_id,
        "packet_sha256": packet.packet_sha256,
        "consumable": True,
        "project_id": packet.project_id,
        "task_plan_id": packet.task_plan_id,
        "task_plan_revision": packet.task_plan_revision,
        "run_id": packet.run_id,
        "sender_agent_id": packet.sender_agent_id,
        "sender_revision": packet.sender_revision,
        "receiver_agent_id": packet.receiver_agent_id,
        "receiver_revision": packet.receiver_revision,
        "authority": packet.authority,
        "budgets": dict(packet.budgets),
        "evidence": packet.evidence,
        "memory_query_plan_sha256": packet.memory_query_plan_sha256,
        "recovery_of": packet.recovery_of,
    }


def persist_handoff_packet(packet: AgentHandoffPacket, path: Path) -> Path:
    """Persist once; immutable identity collisions never overwrite history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(asdict(packet), stream, indent=2, sort_keys=True)
        stream.write("\n")
    return path
