"""Reject evidence locators that depend on paths outside the project."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any


EXTERNAL = re.compile(
    r"(?:\.\./[^\"'\s,\]]+|(?<![A-Za-z])[A-Za-z]:(?:\\\\|\\|/)[^\"'\r\n]+|\\\\[^\\\s]+\\[^\\\s]+(?:\\[^\"'\r\n]*)?|(?i:file://)[^\"'\s]+|(?i:/mnt/[A-Za-z])/[^\"'\r\n]+|(?-i:/Users)/[^\"'\r\n]+|(?i:/(?:home|tmp|var/tmp|private/var))/[^\"'\r\n]+)",
)
STRUCTURED_ROOTS = (
    "evidence",
    "registry",
    "bootstrap",
    "contracts",
    "models",
    "orchestration",
    "policies",
    "extension/evidence",
)
EXCLUDED_PATH_PREFIXES = (
    "evidence/full-control-proof-",
    "evidence/operational-control-fault-",
    "evidence/operational-ui-walk-",
    "evidence/operational-gap-ledger/",
    "registry/operational_gap_ledger",
    "registry/instruction_reconciliation_",
)
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".log", ".toml", ".yaml", ".yml"}
PATH_KEYS = {
    "path",
    "file",
    "filepath",
    "directory",
    "root",
    "source",
    "location",
    "uri",
    "locator",
}
ALLOWED_URI_SCHEMES = {"https", "http", "urn"}


def rewrite_reference_literals(value: object, replacements: dict[str, str]) -> object:
    """Recursively rewrite inert source literals without changing record shape."""
    if isinstance(value, str):
        for source, replacement in replacements.items():
            value = value.replace(source, replacement)
        return value
    if isinstance(value, list):
        return [rewrite_reference_literals(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: rewrite_reference_literals(item, replacements)
            for key, item in value.items()
        }
    return value


def portability_findings(
    text: str, *, allowed_uri_schemes: set[str] = ALLOWED_URI_SCHEMES
) -> tuple[str, ...]:
    findings = []
    for match in EXTERNAL.finditer(text):
        value = match.group(0).rstrip(".,")
        if "://" in value and value.split(":", 1)[0].casefold() in allowed_uri_schemes:
            continue
        findings.append(value)
    return tuple(sorted(set(findings)))


def discover_historical_references(root: Path) -> list[dict[str, Any]]:
    root = root.resolve()
    records = []
    for directory in STRUCTURED_ROOTS:
        for path in sorted((root / directory).rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not path.is_file():
                continue
            if path.suffix.casefold() not in TEXT_SUFFIXES:
                continue
            if "historical" in path.relative_to(root / directory).parts:
                continue
            if path == root / "registry/historical_external_references.json":
                continue
            relative = path.relative_to(root).as_posix()
            if any(relative.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for line_no, line in enumerate(text.splitlines(), 1):
                for locator in portability_findings(line):
                    locator = locator.rstrip("`)]}>,.")
                    if locator.startswith("../"):
                        candidate = (path.parent / locator).resolve()
                        try:
                            candidate.relative_to(root)
                            if candidate.exists():
                                continue
                        except ValueError:
                            pass
                    identifier = hashlib.sha256(
                        f"{relative}:{locator}".encode()
                    ).hexdigest()[:20]
                    records.append(
                        {
                            "id": identifier,
                            "evidence_path": relative,
                            "line": line_no,
                            "external_locator": locator,
                            "classification": "historical_non_authoritative",
                            "runtime_required": False,
                            "disposition": "Preserved as historical provenance only; current release gates use bundled content-addressed evidence and never resolve this locator.",
                        }
                    )
    return records


def validate_evidence_portability(root: Path) -> dict[str, Any]:
    root = root.resolve()
    actual = discover_historical_references(root)
    registry = json.loads(
        (root / "registry/historical_external_references.json").read_text(
            encoding="utf-8"
        )
    )
    errors = []
    if registry.get("records") != actual or registry.get("reference_count") != len(
        actual
    ):
        errors.append("historical external-reference disposition registry is stale")
    for record in actual:
        errors.append(f"{record['id']}: evidence locator is not project-relative")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "reference_count": len(actual),
        "errors": errors,
        "records": actual,
    }
