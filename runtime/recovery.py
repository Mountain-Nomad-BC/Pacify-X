"""Durable lifecycle state with idempotency and non-certifying interruptions."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Iterable


@dataclass(frozen=True, slots=True)
class DurableState:
    package_id: str
    completed_steps: tuple[str, ...]
    selected_skills: tuple[tuple[str, str], ...]
    pending_approvals: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    idempotency_keys: tuple[str, ...]
    interrupted_steps: tuple[str, ...] = ()


def persist_state(state: DurableState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(asdict(state), indent=2) + "\n"
    if path.exists():
        if not path.is_file():
            raise ValueError("durable state target is not a file")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        history = path.parent / ".history" / path.name / f"{stamp}-{digest}.json"
        history.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(history))
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def load_state(path: Path) -> DurableState:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return DurableState(
        payload["package_id"],
        tuple(payload["completed_steps"]),
        tuple(tuple(item) for item in payload["selected_skills"]),
        tuple(payload["pending_approvals"]),
        tuple(payload["evidence_refs"]),
        tuple(payload["idempotency_keys"]),
        tuple(payload.get("interrupted_steps", ())),
    )


def reconcile_resume(
    state: DurableState,
    *,
    actual_evidence: Iterable[str],
    requested_idempotency_key: str | None = None,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if set(state.evidence_refs) - set(actual_evidence):
        reasons.append("recorded evidence is missing from runtime")
    if state.interrupted_steps:
        reasons.append("interrupted steps are non-certifying")
    if (
        requested_idempotency_key
        and requested_idempotency_key in state.idempotency_keys
    ):
        reasons.append("effect idempotency key has already completed")
    return not reasons, tuple(sorted(reasons))
