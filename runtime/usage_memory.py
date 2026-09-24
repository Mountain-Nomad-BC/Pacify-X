"""Governed usage-memory for skills, agents, and workflows.

Owner requirement (2026-09-24): every skill saves usage statistics into a memory file **inside
that skill**, and when a skill is used the stats, success rates, gaps, shortcomings, and issues are
logged to that memory. The same is required for agents and workflows in their own directories.

Design:

    .px/skills/<skill-id>/memory/usage.jsonl     append-only observations
    .px/skills/<skill-id>/memory/stats.json      derived rollup (rebuildable from the log)
    .px/agents/<agent-id>/memory/...             same shape
    .px/workflows/<workflow-id>/memory/...       same shape

Rules this module enforces:

  * the log is **append-only** (observations are evidence, not mutable state);
  * the rollup is **derived** and rebuildable from the log, so it can never become canonical on
    its own;
  * a record **never** contains model output, prompts, secrets, or private memory content --
    only outcome metadata;
  * an unknown subject is **created on first observation**, never fabricated before use;
  * a failure is recorded as a failure; it is never smoothed into a success.

Public entry points:
    record_observation(root, subject_kind, subject_id, observation) -> dict
    read_stats(root, subject_kind, subject_id) -> dict
    rebuild_stats(root, subject_kind, subject_id) -> dict
    list_subjects_with_memory(root, subject_kind) -> list[str]
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

USAGE_SCHEMA = "px.usage-memory/1.0"
RECORD_SCHEMA = "px.usage-observation/1.0"

SUBJECT_KINDS = ("skill", "agent", "workflow")
KIND_ROOT = {
    "skill": Path(".px/skills"),
    # Agents are owned by the agency-agent provider registry; their bodies live under
    # providers/agency_agents/agents/**. A parallel .px/agents tree would be a duplicate
    # authority, so memory is written beside the real agent body instead.
    "agent": Path("providers/agency_agents/agents"),
    "workflow": Path("orchestration/workflows"),
}

# Agent ids are dotted (agency.<domain>.<name>) and locate a body file rather than a directory.
AGENT_REGISTRY = Path("registry/agency_agent_registry.json")

OUTCOMES = ("success", "partial", "failure", "refused", "skipped")
# Dispositions mirror the V3 diagnostic vocabulary so usage memory can carry a classification.
DISPOSITIONS = (
    "PRODUCT_DEFECT", "INTEGRATION_DEFECT", "CONFIGURATION_DEFECT", "GENERATED_STATE_DEFECT",
    "EVIDENCE_STALE_OR_INVALID", "PROBE_OR_TEST_DEFECT", "ENVIRONMENT_UNAVAILABLE",
    "EXPECTED_OFFLINE_BOUNDARY", "OPTIMIZATION_OPPORTUNITY", "NO_PRODUCT_DEFECT",
)

MAX_TEXT = 512
MAX_TAGS = 24
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,191}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, name: str, limit: int = MAX_TEXT) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    if len(value.encode("utf-8")) > limit:
        raise ValueError(f"{name} exceeds its byte bound")
    return value.strip()


def _subject_root(root: Path, kind: str, subject_id: str) -> Path:
    if kind not in SUBJECT_KINDS:
        raise ValueError(f"subject kind must be one of {list(SUBJECT_KINDS)}")
    pattern = _AGENT_ID if kind == "agent" else _ID
    if type(subject_id) is not str or pattern.fullmatch(subject_id) is None:
        raise ValueError("subject id must be a bounded lowercase identifier")
    if kind == "agent":
        # Resolve the agent's declared body path and place memory beside it, preserving the
        # directory the registry already uses.
        registry = root / AGENT_REGISTRY
        if not registry.is_file():
            raise ValueError("agency agent registry is missing; cannot resolve an agent subject")
        payload = json.loads(registry.read_text(encoding="utf-8-sig"))
        row = next((a for a in payload.get("agents", []) if a.get("agent_id") == subject_id), None)
        if row is None:
            raise ValueError(f"agent {subject_id!r} is not declared in the agency agent registry")
        body = root / str(row["path"])
        if not body.is_file():
            raise ValueError(f"agent {subject_id!r} declares a missing body: {row['path']}")
        return body.parent
    return root / KIND_ROOT[kind] / subject_id


def _memory_dir(root: Path, kind: str, subject_id: str) -> Path:
    return _subject_root(root, kind, subject_id) / "memory"


def _validate_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    if type(observation) is not dict:
        raise ValueError("observation must be an object")
    allowed = {
        "outcome", "task_id", "run_id", "correlation_id", "duration_ms", "tokens",
        "success_criteria_met", "gap", "shortcoming", "issue", "disposition", "evidence_ref",
        "notes", "tags", "occurred_at", "subject_revision",
    }
    extra = set(observation) - allowed
    if extra:
        raise ValueError(f"observation has unsupported fields: {sorted(extra)}")

    outcome = observation.get("outcome")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {list(OUTCOMES)}")

    record: dict[str, Any] = {"schema_version": RECORD_SCHEMA, "outcome": outcome}
    for name in ("task_id", "run_id", "correlation_id", "evidence_ref", "subject_revision"):
        if observation.get(name) is not None:
            record[name] = _text(observation[name], name, 256)
    for name in ("gap", "shortcoming", "issue", "notes"):
        if observation.get(name) is not None:
            record[name] = _text(observation[name], name)
    if observation.get("disposition") is not None:
        disposition = observation["disposition"]
        if disposition not in DISPOSITIONS:
            raise ValueError(f"disposition must be one of {list(DISPOSITIONS)}")
        record["disposition"] = disposition
    for name in ("duration_ms",):
        value = observation.get(name)
        if value is not None:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"{name} must be a non-negative finite number")
            record[name] = float(value)
    value = observation.get("tokens")
    if value is not None:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("tokens must be a non-negative integer")
        record["tokens"] = int(value)
    if observation.get("success_criteria_met") is not None:
        if type(observation["success_criteria_met"]) is not bool:
            raise ValueError("success_criteria_met must be boolean")
        record["success_criteria_met"] = bool(observation["success_criteria_met"])
    tags = observation.get("tags")
    if tags is not None:
        if type(tags) not in (list, tuple) or len(tags) > MAX_TAGS:
            raise ValueError("tags must be a bounded list")
        record["tags"] = [_text(tag, "tag", 64) for tag in tags]
    record["occurred_at"] = observation.get("occurred_at") or _now()
    return record


def record_observation(
    root: Path, subject_kind: str, subject_id: str, observation: Mapping[str, Any]
) -> dict[str, Any]:
    """Append one observation to a subject's own memory and refresh its derived rollup."""

    root = root.resolve(strict=True)
    record = _validate_observation(observation)
    memory = _memory_dir(root, subject_kind, subject_id)
    memory.mkdir(parents=True, exist_ok=True)

    log_path = memory / "usage.jsonl"
    # Append-only: never rewrite a prior observation.
    with log_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    stats = rebuild_stats(root, subject_kind, subject_id)
    return {"recorded": record, "stats": stats}


def _load_records(root: Path, kind: str, subject_id: str) -> list[dict[str, Any]]:
    log_path = _memory_dir(root, kind, subject_id) / "usage.jsonl"
    if not log_path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            # A corrupt line is surfaced by the rollup, not silently dropped.
            records.append({"schema_version": RECORD_SCHEMA, "outcome": "failure",
                            "issue": "unparseable usage-memory record", "disposition": "EVIDENCE_STALE_OR_INVALID"})
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def rebuild_stats(root: Path, subject_kind: str, subject_id: str) -> dict[str, Any]:
    """Derive the rollup from the append-only log. The rollup is never canonical."""

    root = root.resolve(strict=True)
    records = _load_records(root, subject_kind, subject_id)

    counts = {outcome: 0 for outcome in OUTCOMES}
    dispositions: dict[str, int] = {}
    gaps: list[dict[str, Any]] = []
    durations: list[float] = []
    total_tokens = 0
    criteria_met = 0

    for record in records:
        outcome = str(record.get("outcome") or "failure")
        counts[outcome] = counts.get(outcome, 0) + 1
        if record.get("disposition"):
            key = str(record["disposition"])
            dispositions[key] = dispositions.get(key, 0) + 1
        for field in ("gap", "shortcoming", "issue"):
            if record.get(field):
                gaps.append({"field": field, "detail": str(record[field])[:200],
                             "occurred_at": record.get("occurred_at")})
        if isinstance(record.get("duration_ms"), (int, float)):
            durations.append(float(record["duration_ms"]))
        if isinstance(record.get("tokens"), int):
            total_tokens += int(record["tokens"])
        if record.get("success_criteria_met") is True:
            criteria_met += 1

    total = len(records)
    successes = counts.get("success", 0)
    # Success rate counts only decisive outcomes; refusals and skips are not successes.
    decisive = sum(counts.get(o, 0) for o in ("success", "partial", "failure"))
    success_rate = round(successes / decisive, 6) if decisive else None

    body = {
        "schema_version": USAGE_SCHEMA,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "record_count": total,
        "outcomes": counts,
        "success_rate": success_rate,
        "success_rate_basis": "successes / (success + partial + failure)",
        "criteria_met_count": criteria_met,
        "total_tokens": total_tokens or None,
        "duration_samples": len(durations),
        "duration_best_ms": round(min(durations), 3) if durations else None,
        "duration_p50_ms": round(sorted(durations)[len(durations) // 2], 3) if durations else None,
        "dispositions": dict(sorted(dispositions.items())),
        "gap_count": len(gaps),
        "gaps": gaps[-20:],
        "last_observed_at": records[-1].get("occurred_at") if records else None,
        "note": (
            "Derived rollup. Rebuildable from memory/usage.jsonl, which is the append-only record. "
            "Contains outcome metadata only: no prompts, model output, secrets, or memory content."
        ),
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    body["stats_sha256"] = digest

    memory = _memory_dir(root, subject_kind, subject_id)
    memory.mkdir(parents=True, exist_ok=True)
    prepared = memory / f".stats.json.{uuid4().hex}.prepared"
    prepared.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(prepared, memory / "stats.json")
    return body


def read_stats(root: Path, subject_kind: str, subject_id: str) -> dict[str, Any]:
    """Read the rollup, rebuilding it if absent or stale against the log."""

    root = root.resolve(strict=True)
    memory = _memory_dir(root, subject_kind, subject_id)
    stats_path = memory / "stats.json"
    if not stats_path.is_file():
        return rebuild_stats(root, subject_kind, subject_id)
    stats = json.loads(stats_path.read_text(encoding="utf-8-sig"))
    log_path = memory / "usage.jsonl"
    logged = len([row for row in log_path.read_text(encoding="utf-8-sig").splitlines() if row.strip()]) if log_path.is_file() else 0
    if stats.get("record_count") != logged:
        # The rollup lags the log: rebuild rather than serve a stale success rate.
        return rebuild_stats(root, subject_kind, subject_id)
    return stats

def list_subjects_with_memory(root: Path, subject_kind: str) -> list[str]:
    """Subject ids that already carry a usage-memory log."""

    root = root.resolve(strict=True)
    if subject_kind == "agent":
        registry = root / AGENT_REGISTRY
        if not registry.is_file():
            return []
        try:
            payload = json.loads(registry.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            return []
        found: list[str] = []
        for row in payload.get("agents", []):
            agent_id = row.get("agent_id")
            body = root / str(row.get("path", ""))
            if isinstance(agent_id, str) and (body.parent / "memory" / "usage.jsonl").is_file():
                found.append(agent_id)
        return sorted(found)
    base = root / KIND_ROOT[subject_kind]
    if not base.is_dir():
        return []
    return sorted(
        child.name for child in base.iterdir()
        if child.is_dir() and (child / "memory" / "usage.jsonl").is_file()
        or child.is_file() and (child.parent / "memory" / "usage.jsonl").is_file()
    )


def ensure_subject_memory(root: Path, subject_kind: str, subject_id: str) -> dict[str, Any]:
    """Create the memory directory and an empty log for a subject that exists."""

    root = root.resolve(strict=True)
    subject_root = _subject_root(root, subject_kind, subject_id)
    if not subject_root.is_dir():
        raise ValueError(f"{subject_kind} {subject_id!r} does not resolve to a directory")
    memory = subject_root / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    log_path = memory / "usage.jsonl"
    if not log_path.is_file():
        log_path.write_text("", encoding="utf-8", newline="\n")
    return rebuild_stats(root, subject_kind, subject_id)