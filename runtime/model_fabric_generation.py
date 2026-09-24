"""Deterministic local-model fabric generation identity.

The generation binds admitted model bytes, runtime-profile identities, and the
configuration documents that influence local model execution.  Timestamps and
live health are intentionally excluded so the identity is stable and cache-safe.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

from .archive_io import reject_path_links
from .model_profile import ModelRuntimeProfile

MAX_GENERATION_MODELS = 128
MAX_POLICY_DOCUMENTS = 64
_HEX = frozenset("0123456789abcdef")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256(value: object, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _HEX for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _identity(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 256:
        raise ValueError(f"{field} must be bounded nonempty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ModelFabricGeneration:
    schema_version: str
    generation_id: str
    model_artifacts: tuple[tuple[str, str], ...]
    runtime_profiles: tuple[tuple[str, str], ...]
    policy_documents: tuple[tuple[str, str], ...]
    adapter_revisions: tuple[tuple[str, str], ...]

    def validate(self) -> None:
        if self.schema_version != "px.model-fabric-generation/1.0":
            raise ValueError("unsupported model fabric generation schema")
        _sha256(self.generation_id, "generation_id")
        for field, rows, limit in (
            ("model_artifacts", self.model_artifacts, MAX_GENERATION_MODELS),
            ("runtime_profiles", self.runtime_profiles, MAX_GENERATION_MODELS),
            ("policy_documents", self.policy_documents, MAX_POLICY_DOCUMENTS),
            ("adapter_revisions", self.adapter_revisions, MAX_POLICY_DOCUMENTS),
        ):
            if type(rows) is not tuple or len(rows) > limit:
                raise ValueError(f"{field} exceeds the generation identity bound")
            seen: set[str] = set()
            for key, digest in rows:
                key = _identity(key, f"{field} key")
                _sha256(digest, f"{field} digest")
                if key in seen:
                    raise ValueError(f"duplicate {field} key")
                seen.add(key)
        expected = _generation_digest(
            self.model_artifacts, self.runtime_profiles, self.policy_documents, self.adapter_revisions
        )
        if expected != self.generation_id:
            raise ValueError("model fabric generation digest is invalid")


def _normalize_pairs(values: Mapping[str, str] | Iterable[tuple[str, str]], *, field: str, limit: int) -> tuple[tuple[str, str], ...]:
    rows = tuple(values.items()) if isinstance(values, Mapping) else tuple(values)
    if len(rows) > limit:
        raise ValueError(f"{field} exceeds the generation identity bound")
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, digest in rows:
        key = _identity(key, f"{field} key")
        digest = _sha256(digest, f"{field} digest")
        if key in seen:
            raise ValueError(f"duplicate {field} key")
        seen.add(key)
        normalized.append((key, digest))
    return tuple(sorted(normalized))


def _generation_digest(
    model_artifacts: tuple[tuple[str, str], ...],
    runtime_profiles: tuple[tuple[str, str], ...],
    policy_documents: tuple[tuple[str, str], ...],
    adapter_revisions: tuple[tuple[str, str], ...],
) -> str:
    body = {
        "schema_version": "px.model-fabric-generation/1.0",
        "model_artifacts": model_artifacts,
        "runtime_profiles": runtime_profiles,
        "policy_documents": policy_documents,
        "adapter_revisions": adapter_revisions,
    }
    return hashlib.sha256(_canonical(body)).hexdigest()


def build_model_fabric_generation(
    *,
    model_artifacts: Mapping[str, str] | Iterable[tuple[str, str]],
    profiles: Iterable[ModelRuntimeProfile],
    policy_documents: Mapping[str, str] | Iterable[tuple[str, str]],
    adapter_revisions: Mapping[str, str] | Iterable[tuple[str, str]] = (),
) -> ModelFabricGeneration:
    model_rows = _normalize_pairs(model_artifacts, field="model_artifacts", limit=MAX_GENERATION_MODELS)
    profile_pairs: list[tuple[str, str]] = []
    for profile in profiles:
        if type(profile) is not ModelRuntimeProfile:
            raise ValueError("typed runtime profiles are required for generation identity")
        profile.validate()
        profile_pairs.append((profile.profile_id, profile.profile_sha256))
    profile_rows = _normalize_pairs(profile_pairs, field="runtime_profiles", limit=MAX_GENERATION_MODELS)
    policy_rows = _normalize_pairs(policy_documents, field="policy_documents", limit=MAX_POLICY_DOCUMENTS)
    adapter_rows = _normalize_pairs(adapter_revisions, field="adapter_revisions", limit=MAX_POLICY_DOCUMENTS)
    generation = ModelFabricGeneration(
        schema_version="px.model-fabric-generation/1.0",
        generation_id=_generation_digest(model_rows, profile_rows, policy_rows, adapter_rows),
        model_artifacts=model_rows,
        runtime_profiles=profile_rows,
        policy_documents=policy_rows,
        adapter_revisions=adapter_rows,
    )
    generation.validate()
    return generation


def policy_document_digests(root: Path) -> dict[str, str]:
    reject_path_links(root)
    relative_paths = (
        "models/routing-policy.json",
        "models/benchmark-policy.json",
        "models/model-portfolio.json",
        "models/runtime-profiles.json",
        "models/resource-policy.json",
        "models/provider-protocols.json",
    )
    result: dict[str, str] = {}
    for relative in relative_paths:
        path = root / relative
        reject_path_links(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        result[relative] = _sha_bytes(path.read_bytes())
    return result
