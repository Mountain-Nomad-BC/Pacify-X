"""Typed dependency observations projected from existing canonical owners.

Identity is semantic owner/kind/key, never physical filename alone. Revision is
the exact observed owner revision and content digest, not an acceptance claim.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from .generated_dependency import dependency_identity as bounded_identity
from .json_io import bounded_canonical_json_bytes

SCHEMA = "px.dependency-identity/1.0"
KINDS = frozenset({"source", "semantic_generation", "model_profile", "provider_config",
    "tool_config", "policy", "authority", "retrieval_index", "execution_graph",
    "agent", "skill", "workflow", "formula", "knowledge", "projection",
    "test", "section", "release_evidence"})


@dataclass(frozen=True, slots=True)
class DependencyIdentity:
    kind: str
    semantic_key: str
    canonical_owner: str
    owner_revision: str
    content_sha256: str
    project_id: str

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError("unsupported dependency kind")
        for field in (self.semantic_key, self.canonical_owner, self.owner_revision, self.project_id):
            bounded_identity(field)
        if type(self.content_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", self.content_sha256) is None:
            raise ValueError("dependency observation requires an exact content SHA-256")

    @property
    def node_id(self):
        return "pxdep:" + hashlib.sha256(bounded_canonical_json_bytes({
            "kind": self.kind, "semantic_key": self.semantic_key,
            "canonical_owner": self.canonical_owner, "project_id": self.project_id},
            max_bytes=32768)).hexdigest()

    @property
    def revision(self):
        return hashlib.sha256(bounded_canonical_json_bytes({"node_id": self.node_id,
            "owner_revision": self.owner_revision, "content_sha256": self.content_sha256},
            max_bytes=32768)).hexdigest()

    def as_dict(self):
        return {"schema_version": SCHEMA, "kind": self.kind, "semantic_key": self.semantic_key,
            "canonical_owner": self.canonical_owner, "owner_revision": self.owner_revision,
            "content_sha256": self.content_sha256, "project_id": self.project_id,
            "node_id": self.node_id, "revision": self.revision, "authority_granted": False}


def read_dependency_identity(record):
    if type(record) is not dict or set(record) != {"schema_version", "kind", "semantic_key",
            "canonical_owner", "owner_revision", "content_sha256", "project_id", "node_id",
            "revision", "authority_granted"} or record.get("schema_version") != SCHEMA:
        raise ValueError("exact typed dependency identity required")
    value = DependencyIdentity(*(record[name] for name in
        ("kind", "semantic_key", "canonical_owner", "owner_revision", "content_sha256", "project_id")))
    if record != value.as_dict():
        raise ValueError("dependency identity or revision digest differs")
    return value
