"""Audit repository source for non-portable absolute path literals.

Reports any source/config file that embeds a machine-specific absolute path
(drive-letter, UNC, or home-directory absolute path) which would break on another
installation. Intended as a pre-release guard.

Usage: python scripts/audit_local_paths.py --root .
Exit code 0 when clean, 1 when offenders are found.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Directories that are not shipped source.
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".venv-certify",
    "node_modules",
    "__pycache__",
    ".tmp",
    ".px",
    ".pacify-x",
    ".px_agent_console_backup",
    "dist",
    "out",
}

# Only these extensions are scanned (source/config that ships).
INCLUDE_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml",
    ".ps1", ".psm1", ".sh", ".cmd", ".bat", ".md",
}

# Generated/large data files that are not authored source.
EXCLUDE_NAMES = {
    "operational_gap_ledger.jsonl",
    "operational_gap_ledger.snapshot.json",
    "file-facts.jsonl",
    "configuration-map.json",
}
MAX_FILE_BYTES = 512 * 1024

# Absolute-path patterns that are NOT portable.
PATTERNS = (
    ("windows_drive", re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/](?!\\)")),
    ("unc_path", re.compile(r"\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9._$-]+")),
    ("posix_home", re.compile(r"(?<![\w.])/(?:home|Users)/[A-Za-z0-9._-]+/")),
)

# Files/directories that are immutable evidence or documentation examples and are not
# authored product source; a literal path here is data, not a portability defect.
EVIDENCE_PREFIXES = ("evidence/", "registry/instruction_reconciliation_audit_", "registry/operational_gap_ledger")
DOC_PREFIXES = ("docs/R01_", "docs/R10_")
# Files that legitimately contain absolute-path patterns by design:
#   - test fixtures that assert path rejection
#   - the portability detector itself (its regex must match external paths)
ALLOW_FILES = ("runtime/evidence_portability.py",)

# Known-safe literals: version strings, regexes, URLs, escapes, generic examples.
ALLOW_MARKERS = (
    "C:\\\\",            # escaped regex literal in a string
    "http://",
    "https://",
    "schemas",
    "C:\\path\\to",      # generic documentation placeholder
    "C:\\delivery\\",    # generic documentation placeholder
)


def _iter_files(root: Path):
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            try:
                if entry.is_dir():
                    if name in EXCLUDE_DIRS or name.startswith(".tmp_"):
                        continue
                    stack.append(entry)
                    continue
                if not entry.is_file():
                    continue
            except OSError:
                continue
            if entry.suffix.casefold() not in INCLUDE_SUFFIXES:
                continue
            if name in EXCLUDE_NAMES:
                continue
            try:
                if entry.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield entry


def _looks_like_regex_escape(line: str) -> bool:
    r"""True when a backslash chain is a regex literal, not a filesystem path.

    Chromium-style stderr patterns such as ``electron\\shell\\browser\\api`` and
    ``\.cc`` use doubled backslashes inside a regex literal; a real UNC path would not
    contain a ``\.`` escape.
    """
    return bool(re.search(r"\\\.", line) or re.search(r"\\[a-z_]+", line))


def audit(root: Path) -> dict:
    findings: list[dict[str, object]] = []
    scanned = 0
    for path in _iter_files(root):
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            if any(marker in line for marker in ALLOW_MARKERS):
                continue
            for label, pattern in PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append(
                        {
                            "path": relative,
                            "line": number,
                            "kind": label,
                            "match": match.group(0),
                        }
                    )
    return {
        "schema_version": "px.local-path-audit/1.0",
        "valid": not findings,
        "scanned_root": ".",
        "files_scanned": scanned,
        "finding_count": len(findings),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    # Scan the shipped source/config areas explicitly rather than walking the whole
    # tree (which includes .git objects, node_modules, and multi-GB model custody).
    areas = ["runtime", "scripts", "tests", "extension/src", "extension/scripts",
             "extension/media", "extension/tests", "px", "docs", "registry",
             "models", "contracts", "policies", "bootstrap", "evidence"]
    findings: list[dict[str, object]] = []
    scanned = 0
    for area in areas:
        area_path = root / area
        if not area_path.exists():
            continue
        for path in _iter_files(area_path):
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            relative = path.relative_to(root).as_posix()
            if relative.startswith(EVIDENCE_PREFIXES) or relative.startswith(DOC_PREFIXES):
                continue
            if relative.startswith(("tests/", "extension/tests/")):
                continue
            if relative in ALLOW_FILES:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if any(marker in line for marker in ALLOW_MARKERS):
                    continue
                if _looks_like_regex_escape(line):
                    continue
                for label, pattern in PATTERNS:
                    match = pattern.search(line)
                    if match:
                        findings.append({"path": relative, "line": number, "kind": label, "match": match.group(0)})
    result = {
        "schema_version": "px.local-path-audit/1.0",
        "valid": not findings,
        "scanned_areas": [a for a in areas if (root / a).exists()],
        "files_scanned": scanned,
        "finding_count": len(findings),
        "findings": findings,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"local-path audit: valid={result['valid']} files={scanned} findings={result['finding_count']}")
        for finding in result["findings"][:200]:
            print(f"  {finding['path']}:{finding['line']} [{finding['kind']}] {finding['match']}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())