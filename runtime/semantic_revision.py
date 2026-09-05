"""Separate immutable byte identity from bounded semantic identity."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable

import yaml


CANONICALIZER_REVISION = "px.semantic-canonicalizer/1.0"


@dataclass(frozen=True, slots=True)
class SemanticRevision:
    byte_revision: str
    semantic_revision: str | None
    effective_revision: str
    semantic_supported: bool
    artifact_type: str
    canonicalizer: str | None
    canonicalizer_revision: str


def _json_canonical(data: bytes) -> bytes:
    value = json.loads(data.decode("utf-8"))
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _yaml_canonical(data: bytes) -> bytes:
    value = yaml.safe_load(data.decode("utf-8"))
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _python_canonical(data: bytes) -> bytes:
    tree = ast.parse(data.decode("utf-8"))
    return ast.dump(tree, annotate_fields=True, include_attributes=False).encode("utf-8")


_CANONICALIZERS: dict[str, tuple[str, Callable[[bytes], bytes]]] = {
    ".json": ("canonical-json", _json_canonical),
    ".yaml": ("canonical-yaml", _yaml_canonical),
    ".yml": ("canonical-yaml", _yaml_canonical),
    ".py": ("python-ast", _python_canonical),
}


def compute_semantic_revision(
    content: bytes | str,
    *,
    artifact_type: str,
) -> SemanticRevision:
    """Compute byte and semantic revisions without guessing unsupported formats.

    ``artifact_type`` is an extension (``.json``) or a filename.  Invalid
    supported content fails closed instead of falling back to a misleading
    semantic hash.  Unsupported formats retain the byte revision as the only
    effective identity.
    """
    data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    byte_revision = hashlib.sha256(data).hexdigest()
    suffix = (
        artifact_type.casefold()
        if artifact_type.startswith(".")
        else Path(artifact_type).suffix.casefold()
    )
    entry = _CANONICALIZERS.get(suffix)
    if entry is None:
        return SemanticRevision(
            byte_revision,
            None,
            byte_revision,
            False,
            suffix or artifact_type.casefold(),
            None,
            CANONICALIZER_REVISION,
        )
    name, canonicalize = entry
    canonical = canonicalize(data)
    semantic_revision = hashlib.sha256(canonical).hexdigest()
    return SemanticRevision(
        byte_revision,
        semantic_revision,
        semantic_revision,
        True,
        suffix,
        name,
        CANONICALIZER_REVISION,
    )
