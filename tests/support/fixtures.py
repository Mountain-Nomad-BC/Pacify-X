"""Shared fixtures for the PX-AUD memory-broker and scheduler regression modules.

`tests/test_memory_broker.py` and `tests/test_memory_broker_regression.py` previously
carried byte-identical copies of `_record()` and `_plan()`, and
`tests/test_scheduler_path_regression.py` and `tests/test_scheduler_regression.py`
carried byte-identical copies of a scheduler test. Duplicated logic is reported by
`runtime.structural_integrity._logic_duplicates`, so the single canonical copy lives
here and both owners import it.

The values below are exactly those used by the original modules; do not "tidy" them,
because PX-AUD-069/070/073 assert on the validation errors these values produce.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from runtime.memory_broker import build_memory_query_plan
from runtime.memory_fabric import MemoryRecord

ROOT = Path(__file__).resolve().parents[1]

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def scheduler_snapshot(**overrides) -> dict:
    '''Shared pressure-telemetry snapshot for PX-AUD-074 and PX-AUD-076.

    Canonical copy: `tests/test_scheduler_regression.py` (074) and
    `tests/test_scheduler_path_regression.py` (076) had byte-identical copies,
    which `runtime.structural_integrity._logic_duplicates` reports as duplicated
    logic. Values must stay exactly as the original audits specify.
    '''
    base = {
        "memory_percent": 50.0,
        "gpu_percent": 30.0,
        "wsl_memory_percent": 40.0,
        "docker_memory_percent": 40.0,
        "agents": 1,
    }
    base.update(overrides)
    return base

def telemetry() -> dict:
    '''Admission pressure telemetry used by PX-AUD-075 recovery tests.

    Canonical copy of the literal dict repeated across the recovery cases; the
    values must stay exactly as the original audit specifies.
    '''
    return {
        "memory_percent": 50,
        "gpu_percent": 30,
        "wsl_memory_percent": 40,
        "docker_memory_percent": 40,
        "agents": 1,
    }

def record(memory_id: str, **changes: object) -> MemoryRecord:
    values = {
        "memory_id": memory_id, "workspace_id": "workspace", "project_id": "project",
        "owner_id": "actor", "session_id": "session", "lease_id": "lease",
        "title": "Decision", "memory_type": "decision", "summary": "Use bounded proof",
        "source_artifact": "evidence.json", "source_sha256": "a" * 64,
        "evidence_locator": "evidence:one", "epistemic_status": "observation",
        "confidence": 0.9, "confidence_method": "direct", "classification": "internal",
        "acl": ("project", "actor"), "observed_at": NOW, "effective_at": NOW,
        "certification_status": "certified", "retrieval_enabled": True, "layer": "L1",
        "visibility": "project", "priority": 80,
    }
    values.update(changes)
    return MemoryRecord(**values)


def plan(**changes):
    values = {
        "project_id": "project", "subject_id": "task", "actor_id": "actor",
        "agent_id": "agent", "binding_ids": ("memory:one",),
        "memory_classes": ("decision",), "tiers": ("L1",), "max_items": 2,
        "max_bytes": 4096, "max_tokens": 1024, "trust_floor": 0.8,
        "max_age_seconds": 3600, "conflict_policy": "quarantine",
        "provenance_required": True, "writeback_policy": "deny",
        "source_revision": "source-1", "dependency_revisions": {"memory": "revision-1"},
    }
    values.update(changes)
    return build_memory_query_plan(**values)
