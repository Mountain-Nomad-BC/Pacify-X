"""Deterministic, conservative classification of repository changes."""

from __future__ import annotations

from enum import IntEnum
import re
import json
import time
from pathlib import Path
from .numeric_inputs import (
    bounded_text,
    bounded_sequence,
    bounded_mapping,
    bounded_json_value,
)
from .input_files import relative_source_path, check_deadline
from .archive_io import member_identity, reject_path_links
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
_AUTHORITY_MARKERS = (
    "authority",
    "ownership",
    "admission",
    "effect-grant",
    "effect_grant",
    "operational_gap_ledger",
)


def _text(value, name, maximum=512):
    value = bounded_text(value, name, maximum=maximum, strip=False)
    if not value.strip():
        raise ValueError(name + " must not be whitespace only")
    return value


def _labels(value, name):
    bounded_sequence(value, name, maximum=256)
    result = [_text(item, name) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(name + " must not contain duplicates")
    return result


def _infer(path: str, symbols: Sequence[str], effects: Sequence[str]):
    lowered = path.casefold()
    impacts = []

    def add(condition, category, reason):
        if condition:
            impacts.append((category, reason))

    components = lowered.split("/")
    release_tokens = [re.split(r"[^a-z0-9]+", component) for component in components]
    release_named = any(
        "version" in tokens
        or any(
            tokens[i : i + 2] in (["release", "identity"], ["release", "campaign"])
            for i in range(len(tokens) - 1)
        )
        for tokens in release_tokens
    )
    add(
        components[-1] in {"package.json", "package-lock.json"}
        or lowered.endswith(".vsix")
        or release_named,
        ChangeClass.RELEASE_CRITICAL,
        "release_identity_or_artifact_surface",
    )
    add(
        lowered == "agents.md"
        or lowered.startswith("policies/")
        or any(marker in lowered for marker in _AUTHORITY_MARKERS),
        ChangeClass.AUTHORITY,
        "authority_or_policy_surface",
    )
    add(
        lowered.startswith("contracts/") or lowered.endswith(".schema.json"),
        ChangeClass.SCHEMA,
        "contract_schema_surface",
    )
    add(bool(effects), ChangeClass.RUNTIME, "declared_effect_surface")
    add(
        lowered.startswith(_RUNTIME_PREFIXES),
        ChangeClass.RUNTIME,
        "runtime_implementation_surface",
    )
    add(
        lowered.startswith(("tests/", "extension/tests/")),
        ChangeClass.BEHAVIORAL,
        "behavioral_proof_surface",
    )
    add(
        lowered.startswith(_SEMANTIC_PREFIXES) or bool(symbols),
        ChangeClass.SEMANTIC,
        "semantic_or_symbol_surface",
    )
    add(
        lowered.startswith(("registry/", ".engineering-bootstrap/")),
        ChangeClass.METADATA_ONLY,
        "metadata_projection_surface",
    )
    add(
        lowered.endswith((".md", ".txt", ".rst")),
        ChangeClass.DOC_ONLY,
        "documentation_surface",
    )
    # Supplied symbols/effects cannot make an otherwise unknown path less risky.
    path_reasons = {reason for _, reason in impacts} - {
        "declared_effect_surface",
        "semantic_or_symbol_surface",
    }
    if not path_reasons and not lowered.startswith(_SEMANTIC_PREFIXES):
        impacts.append(
            (ChangeClass.RELEASE_CRITICAL, "unknown_surface_conservative_fallback")
        )
    highest = max(category for category, _ in impacts)
    reason = next(reason for category, reason in impacts if category == highest)
    return highest, reason, [reason for _, reason in impacts]


def _override(record, inferred):
    value = record.get("override_class")
    if value is None:
        if "override_class" in record or "override_evidence" in record:
            raise ValueError("override metadata requires an actual selected class")
        return None
    if type(value) is list:
        raise ValueError("conflicting change-class overrides are forbidden")
    _text(value, "override class", maximum=32)
    try:
        selected = ChangeClass[value]
    except KeyError as error:
        raise ValueError("unknown change-class override") from error
    evidence = bounded_mapping(
        record.get("override_evidence"), "override evidence", maximum=4
    )
    if set(evidence) != {"reference", "sha256", "approved_by", "rationale"}:
        raise ValueError("override evidence fields must be exact")
    _text(evidence["reference"], "override reference", maximum=4096)
    _text(evidence["approved_by"], "override approver")
    _text(evidence["rationale"], "override rationale")
    if not _HASH.fullmatch(_text(evidence["sha256"], "override hash", maximum=64)):
        raise ValueError("override evidence must be reference/hash bound")
    if selected < inferred:
        raise ValueError("change-class override cannot reduce inferred proof")
    return selected, "declared_risk_increase"


class _Budget:
    def __init__(self, deadline):
        self.deadline = deadline
        self.used = 0

    def add(self, value):
        check_deadline(self.deadline)
        bounded_json_value(value)
        self.used += (
            len(
                json.dumps(
                    value, ensure_ascii=True, separators=(",", ":"), allow_nan=False
                )
            )
            + 16
        )
        if self.used > 8 * 1024 * 1024:
            raise ValueError("classification aggregate byte budget exhausted")
        check_deadline(self.deadline)


def classify_changes(
    changes: Sequence[Mapping[str, object]], *, root: Path | None = None
) -> dict[str, object]:
    """Classify supplied metadata at maximum impact; never verify a Git diff.

    Optional root containment checks original path components without acquiring
    file bodies or pinning ancestor handles. Overrides are supplied declarations,
    not authenticated approval. No persistent cache or execution authority exists.
    """
    deadline = time.monotonic() + 60.0
    bounded_sequence(changes, "changes", maximum=10000, minimum=1)
    inputs = []
    input_budget = _Budget(deadline)
    identities = set()
    for record in changes:
        bounded_mapping(record, "change record", maximum=5)
        if not set(record) <= {
            "path",
            "symbols",
            "effects",
            "override_class",
            "override_evidence",
        }:
            raise ValueError("unsupported change metadata fields")
        path = relative_source_path(
            _text(record.get("path"), "change path", maximum=4096).replace("\\", "/")
        )
        identity = member_identity(path, allow_directory=False)
        if identity in identities:
            raise ValueError("duplicate change path or portable alias")
        identities.add(identity)
        normalized = {
            "path": path,
            "symbols": _labels(record.get("symbols", ()), "symbols"),
            "effects": _labels(record.get("effects", ()), "effects"),
        }
        for field in ("override_class", "override_evidence"):
            if field in record:
                normalized[field] = record[field]
        # Validate typed override fields before any generic JSON traversal.
        _override(normalized, ChangeClass.DOC_ONLY)
        input_budget.add(normalized)
        inputs.append(normalized)
    bounded_json_value(inputs)
    check_deadline(deadline)
    checked_root = None
    if root is not None:
        if not isinstance(root, Path):
            raise ValueError("classification root must be a Path")
        _text(str(root), "classification root", maximum=4096)
        reject_path_links(root)
        if not root.is_dir():
            raise ValueError("classification root must be an existing directory")
        checked_root = root.resolve(strict=True)
    records = []
    output_budget = _Budget(deadline)
    for record in inputs:
        check_deadline(deadline)
        path = record["path"]
        if checked_root is not None:
            # Keep the supplied spelling for link checks before resolution.
            target = root / path
            reject_path_links(root)
            reject_path_links(target)
            if not target.resolve(strict=False).is_relative_to(checked_root):
                raise ValueError("change path escapes supplied root")
            if target.exists() and not target.is_file():
                raise ValueError("change path must denote a file or deleted locator")
        inferred, reason, reasons = _infer(path, record["symbols"], record["effects"])
        override = _override(record, inferred)
        selected, selected_reason = override or (inferred, reason)
        result = {
            "path": path,
            "change_class": selected.name,
            "inferred_class": inferred.name,
            "reason": selected_reason,
            "inferred_reasons": reasons,
            "override_evidence_verified": False,
            "owner": "runtime/change_classification.py",
        }
        output_budget.add(result)
        records.append(result)
    highest = max(ChangeClass[item["change_class"]] for item in records)
    result = {
        "schema_version": "px.change-classification/1.0",
        "change_class": highest.name,
        "records": records,
        "mixed": len({item["change_class"] for item in records}) > 1,
        "owner": "runtime/change_classification.py",
        "diff_verified": False,
        "path_boundary": "supplied_root_checked"
        if checked_root is not None
        else "portable_metadata_only",
    }
    bounded_json_value(result)
    check_deadline(deadline)
    return result
