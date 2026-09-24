"""Read-only operational artifacts projected from authoritative PX objects."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Iterable, Mapping


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: object, label: str, maximum: int = 16384) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{label} must be bounded nonempty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class OperationalArtifact:
    artifact_id: str
    artifact_type: str
    title: str
    text: str
    aliases: tuple[str, ...]
    authority_id: str
    authority_revision: str
    role_visibility: tuple[str, ...] = ("public",)
    graph_edges: tuple[tuple[str, str, str], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority_granted: bool = False

    def __post_init__(self) -> None:
        for label, value in (("artifact_id", self.artifact_id), ("artifact_type", self.artifact_type), ("title", self.title), ("authority_id", self.authority_id), ("authority_revision", self.authority_revision)):
            _text(value, label, 4096)
        if type(self.text) is not str or len(self.text.encode("utf-8")) > 65536:
            raise ValueError("projection text exceeds byte budget")
        if type(self.authority_granted) is not bool or self.authority_granted:
            raise ValueError("operational projections cannot grant authority")
        for values, label in ((self.aliases, "aliases"), (self.role_visibility, "role_visibility")):
            if type(values) is not tuple or any(type(item) is not str or not item.strip() for item in values):
                raise ValueError(f"{label} must be nonempty-text tuples")
        if type(self.graph_edges) is not tuple or len(self.graph_edges) > 10000:
            raise ValueError("graph_edges must be a bounded tuple")
        for edge in self.graph_edges:
            if type(edge) is not tuple or len(edge) != 3 or any(type(item) is not str or not item.strip() for item in edge):
                raise ValueError("graph edge must be a source/relation/target tuple")
        _canonical(dict(self.metadata))

    @property
    def artifact_sha256(self) -> str:
        return _sha({
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "title": self.title,
            "text": self.text,
            "aliases": list(self.aliases),
            "authority_id": self.authority_id,
            "authority_revision": self.authority_revision,
            "role_visibility": list(self.role_visibility),
            "graph_edges": [list(edge) for edge in self.graph_edges],
            "metadata": dict(self.metadata),
            "authority_granted": False,
        })

    @property
    def artifact_hash(self) -> str:
        return self.artifact_sha256


def project_action_descriptor(action: Mapping[str, Any], *, revision: str) -> OperationalArtifact:
    action_id = _text(action.get("action_id"), "action_id", 512)
    title = str(action.get("description") or action_id)
    aliases = tuple(str(item) for item in action.get("aliases", ()))
    tags = tuple(str(item) for item in action.get("tags", ()))
    return OperationalArtifact(
        artifact_id=f"action:{action_id}", artifact_type="action", title=title,
        text=" ".join(item for item in (action_id, title, *aliases, *tags) if item), aliases=aliases,
        authority_id=action_id, authority_revision=_text(revision, "revision", 512),
        role_visibility=tuple(str(item) for item in action.get("allowed_roles", ())) or ("public",),
        metadata={"mutating": action.get("mutating") is True, "risk_level": str(action.get("risk_level") or "R1"), "queue_eligible": action.get("queue_eligible") is True},
    )


def project_workflow_contract(workflow: Mapping[str, Any], *, revision: str) -> tuple[OperationalArtifact, ...]:
    workflow_id = _text(workflow.get("workflow_id"), "workflow_id", 512)
    title = str(workflow.get("title") or workflow_id)
    steps = workflow.get("steps", ())
    if not isinstance(steps, (list, tuple)) or len(steps) > 10000:
        raise ValueError("workflow steps must be a bounded list")
    artifacts: list[OperationalArtifact] = [OperationalArtifact(
        artifact_id=f"workflow:{workflow_id}", artifact_type="workflow_overview", title=title,
        text=" ".join([title, str(workflow.get("description") or ""), *(str(step.get("name") or step.get("step_id") or "") for step in steps if isinstance(step, Mapping))]),
        aliases=tuple(str(item) for item in workflow.get("aliases", ())), authority_id=workflow_id, authority_revision=revision,
        metadata={"step_count": len(steps)},
    )]
    for index, step in enumerate(steps, 1):
        if not isinstance(step, Mapping):
            raise ValueError("workflow step must be a mapping")
        step_id = str(step.get("step_id") or f"step_{index}")
        artifacts.append(OperationalArtifact(
            artifact_id=f"workflow:{workflow_id}:step:{step_id}", artifact_type="workflow_step", title=str(step.get("name") or step_id),
            text=" ".join(str(item) for item in (step_id, step.get("name", ""), step.get("description", "")) if item), aliases=(), authority_id=workflow_id, authority_revision=revision,
            graph_edges=((f"workflow:{workflow_id}", "has_step", f"workflow:{workflow_id}:step:{step_id}"),), metadata={"ordinal": index},
        ))
    return tuple(artifacts)


def projection_manifest(artifacts: Iterable[OperationalArtifact]) -> dict[str, Any]:
    rows = tuple(artifacts)
    if any(type(row) is not OperationalArtifact for row in rows):
        raise ValueError("projection_manifest requires OperationalArtifact records")
    ids = [row.artifact_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("operational projection contains duplicate artifact IDs")
    items = [[row.artifact_id, row.artifact_sha256, row.authority_id, row.authority_revision] for row in sorted(rows, key=lambda item: item.artifact_id)]
    return {"schema_version": "1.0", "artifact_count": len(items), "projection_sha256": _sha(items), "artifacts": items, "authority_granted": False}


def retrieval_source_mapping(artifact: OperationalArtifact) -> dict[str, Any]:
    if type(artifact) is not OperationalArtifact:
        raise ValueError("typed OperationalArtifact required")
    return {
        "source_id": artifact.artifact_id,
        "title": artifact.title,
        "text": artifact.text,
        "visibility": artifact.role_visibility,
        "lineage": f"projection:{artifact.authority_id}@{artifact.authority_revision}",
        "kind": artifact.artifact_type,
        "links": tuple(edge[2] for edge in artifact.graph_edges),
        "metadata": {**dict(artifact.metadata), "authority_id": artifact.authority_id, "authority_revision": artifact.authority_revision, "projection_sha256": artifact.artifact_sha256, "exact_keys": [artifact.artifact_id, artifact.authority_id, *artifact.aliases], "authority_granted": False},
        "structured": {"artifact_type": artifact.artifact_type, "aliases": list(artifact.aliases)},
        "source_revision": artifact.authority_revision,
    }
