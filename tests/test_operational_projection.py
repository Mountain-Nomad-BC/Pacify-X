from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from runtime.cognitive_core.index_builder import operational_artifacts_to_cognitive_records
from runtime.event_ledger import append_operational_lifecycle_event, validate_event_ledger
from runtime.operational_projection import OperationalArtifact, project_action_descriptor, projection_manifest, retrieval_source_mapping
from runtime.workflow_studio import workflow_operational_projection

H = "a" * 64


def test_operational_projection_is_read_only_and_searchable() -> None:
    artifact = project_action_descriptor({"action_id": "cap.read", "description": "Read data", "aliases": ["show data"], "mutating": False}, revision=H)
    assert artifact.authority_granted is False
    mapping = retrieval_source_mapping(artifact)
    assert mapping["metadata"]["authority_granted"] is False
    rows = operational_artifacts_to_cognitive_records((artifact,))
    assert rows[0]["kind"] == "operational_projection"
    assert rows[0]["authority_granted"] is False


def test_projection_manifest_is_deterministic() -> None:
    artifact = OperationalArtifact("a", "test", "A", "text", (), "owner", H)
    assert projection_manifest((artifact,)) == projection_manifest((artifact,))


@dataclass(frozen=True)
class FakeWorkflow:
    workflow_id: str = "wf.test"
    version: str = "1.0.0"
    owner: str = "test"
    nodes: tuple = ()
    edges: tuple = ()
    lifecycle: str = "admitted"


def test_workflow_projection_does_not_mutate_studio_state() -> None:
    projected = workflow_operational_projection(FakeWorkflow(), revision_sha256=H)
    assert projected["authority_granted"] is False
    assert projected["projection"]["artifact_count"] == 1


def test_operational_lifecycle_event_is_chained(tmp_path: Path) -> None:
    ledger = tmp_path / "events"
    append_operational_lifecycle_event(ledger, lifecycle="projection", subject_id="cap.read", subject_revision=H, evidence_sha256="b" * 64)
    report = validate_event_ledger(ledger)
    assert report["valid"]
    assert report["event_count"] == 1
