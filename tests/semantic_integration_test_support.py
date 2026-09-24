from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from runtime.memory_fabric import MemoryRecord
from runtime.semantic_integration_types import QueryAuthorization


def make_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "alpha.py").write_text(
        "class Engine:\n    def run(self, value: int) -> int:\n        return helper(value)\n\ndef helper(value: int) -> int:\n    return value + 1\n",
        encoding="utf-8",
    )
    return root


def auth(project_id: str, *operations: str) -> QueryAuthorization:
    return QueryAuthorization("token-1", "actor-1", (project_id,), tuple(operations))


def memory_record(*, memory_id: str = "mem-1", project_id: str = "p1", revision: int = 2) -> MemoryRecord:
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    return MemoryRecord(
        memory_id=memory_id, workspace_id="ws", project_id=project_id, owner_id="owner",
        session_id="session", lease_id="lease", title="Fact", memory_type="fact",
        summary="A durable memory", source_artifact="artifact", source_sha256="a" * 64,
        evidence_locator="evidence:1", epistemic_status="observation", confidence=0.95,
        confidence_method="test", classification="internal", acl=("actor-1",),
        observed_at=now, effective_at=now, revision=revision, certification_status="certified",
        retrieval_enabled=True, layer="L1", visibility="project",
    )


def memory_location(record: MemoryRecord, *, tier: str = "hot", locator: str = "memory/hot/mem-1.json", location_revision: int = 3):
    # Wave 4 owns physical memory relocation.  Import it only when a Wave-4 test asks
    # for a location so the shared support module remains valid in a Wave-3-only tree.
    from runtime.semantic_memory_relocation import MemoryLocation

    return MemoryLocation(record.memory_id, record.project_id, tier, locator, location_revision, record.revision, record.source_sha256)


def fusion_auth(project_id: str, *, include_project_map: bool = False) -> QueryAuthorization:
    operations = [
        "semantic.cross_project.query",
        "semantic.symbol.find",
        "semantic.knowledge.fuse",
        "semantic.model.context",
    ]
    if include_project_map:
        operations.append("semantic.project_map.query")
    return auth(project_id, *operations)
