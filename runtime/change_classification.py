"""Deterministic, conservative classification of repository changes."""

from __future__ import annotations

from enum import IntEnum
import re
from typing import Mapping, Sequence


class ChangeClass(IntEnum):
    DOC_ONLY = 0
    METADATA_ONLY = 1
    SEMANTIC = 2
    BEHAVIORAL = 3
    SCHEMA = 4
    AUTHORITY = 5
    RUNTIME = 6
    RELEASE_CRITICAL = 7


_HASH = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_PREFIXES = ("runtime/", "extension/src/", "extension/server/", "scripts/")
_SEMANTIC_PREFIXES = (
    ".px/skills/",
    "orchestration/",
    "providers/",
    "prompts/",
    "models/",
)
_RELEASE_MARKERS = (
    "release_identity",
    "release-campaign",
    "release_campaign",
    "package.json",
    "package-lock.json",
    ".vsix",
    "version",
)
_AUTHORITY_MARKERS = (
    "authority",
    "ownership",
    "admission",
    "effect-grant",
    "effect_grant",
    "operational_gap_ledger",
)


def _infer(path: str, symbols: Sequence[str], effects: Sequence[str]) -> tuple[ChangeClass, str]:
    normalized = path.strip().replace("\\", "/")
    lowered = normalized.casefold()
    if not normalized:
        return ChangeClass.RELEASE_CRITICAL, "missing_path_conservative_fallback"
    if any(marker in lowered for marker in _RELEASE_MARKERS):
        return ChangeClass.RELEASE_CRITICAL, "release_identity_or_artifact_surface"
    if lowered == "agents.md" or lowered.startswith("policies/") or any(
        marker in lowered for marker in _AUTHORITY_MARKERS
    ):
        return ChangeClass.AUTHORITY, "authority_or_policy_surface"
    if lowered.startswith("contracts/") or lowered.endswith(".schema.json"):
        return ChangeClass.SCHEMA, "contract_schema_surface"
    if effects:
        return ChangeClass.RUNTIME, "declared_effect_surface"
    if lowered.startswith(_RUNTIME_PREFIXES):
        return ChangeClass.RUNTIME, "runtime_implementation_surface"
    if lowered.startswith("tests/") or lowered.startswith("extension/tests/"):
        return ChangeClass.BEHAVIORAL, "behavioral_proof_surface"
    if lowered.startswith(_SEMANTIC_PREFIXES) or symbols:
        return ChangeClass.SEMANTIC, "semantic_or_symbol_surface"
    if lowered.startswith("registry/") or lowered.startswith(".engineering-bootstrap/"):
        return ChangeClass.METADATA_ONLY, "metadata_projection_surface"
    if lowered.endswith(('.md', '.txt', '.rst')):
        return ChangeClass.DOC_ONLY, "documentation_surface"
    return ChangeClass.RELEASE_CRITICAL, "unknown_surface_conservative_fallback"


def _override(record: Mapping[str, object], inferred: ChangeClass) -> tuple[ChangeClass, str] | None:
    value = record.get("override_class")
    if value is None:
        return None
    if isinstance(value, list):
        raise ValueError("conflicting change-class overrides are forbidden")
    try:
        selected = ChangeClass[str(value)]
    except KeyError as error:
        raise ValueError(f"unknown change-class override: {value}") from error
    evidence = record.get("override_evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("change-class override requires evidence")
    if not evidence.get("reference") or not _HASH.fullmatch(
        str(evidence.get("sha256") or "")
    ):
        raise ValueError("change-class override evidence must be reference/hash bound")
    if not evidence.get("approved_by") or not evidence.get("rationale"):
        raise ValueError("change-class override requires approval and rationale")
    if selected < inferred:
        raise ValueError("change-class override cannot reduce inferred proof")
    return selected, "evidence_bound_risk_increase"


def classify_changes(changes: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Classify each change and return the highest required proof class."""
    if not changes:
        raise ValueError("at least one change is required")
    records: list[dict[str, object]] = []
    for record in changes:
        path = str(record.get("path") or "")
        symbols_value = record.get("symbols", ())
        effects_value = record.get("effects", ())
        symbols = tuple(map(str, symbols_value)) if isinstance(symbols_value, (list, tuple)) else ()
        effects = tuple(map(str, effects_value)) if isinstance(effects_value, (list, tuple)) else ()
        inferred, reason = _infer(path, symbols, effects)
        override = _override(record, inferred)
        selected, selected_reason = override or (inferred, reason)
        records.append(
            {
                "path": path.replace("\\", "/"),
                "change_class": selected.name,
                "inferred_class": inferred.name,
                "reason": selected_reason,
                "owner": "runtime/change_classification.py",
            }
        )
    highest = max(ChangeClass[item["change_class"]] for item in records)
    return {
        "schema_version": "px.change-classification/1.0",
        "change_class": highest.name,
        "records": records,
        "mixed": len({item["change_class"] for item in records}) > 1,
        "owner": "runtime/change_classification.py",
    }
