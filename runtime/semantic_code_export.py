"""Deterministic, non-authoritative export of semantic index evidence."""

from __future__ import annotations

import json
from pathlib import Path

from .semantic_code_index import SemanticProjectIndex


def semantic_index_payload(index: SemanticProjectIndex) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "authority": "derived_non_authoritative",
        "project_root": index.project_root,
        "revision": index.revision,
        "summary": index.as_summary(),
        "documents": [item.as_dict() for item in index.documents],
        "references": [item.as_dict() for item in index.references],
    }


def write_semantic_index(index: SemanticProjectIndex, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = semantic_index_payload(index)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(destination)
    return destination
