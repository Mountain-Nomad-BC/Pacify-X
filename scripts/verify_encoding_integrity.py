"""Text/encoding integrity gate.

Promoted from the temporary BOM audit that found a real defect during this campaign: PowerShell
`Set-Content -Encoding UTF8` silently wrote a UTF-8 BOM into `runtime-lock.json` and three test
files, breaking JSON parsing and `ast.parse`. A temporary script is not a control; this is.

Detects, in governed text:

  * prohibited UTF-8 BOMs;
  * invalid UTF-8;
  * NUL / control bytes that do not belong in text;
  * JSON parse failures;
  * Python AST failures;
  * TOML parse failures;
  * YAML parse failures where a parser is available.

Historical evidence documents may legitimately contain mojibake and are explicitly
allow-listed rather than silently skipped — so the allowlist is visible and reviewable.

Usage:
    python scripts/verify_encoding_integrity.py --root .
    python scripts/verify_encoding_integrity.py --root . --json
Exit 0 when clean, 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from pathlib import Path

SCHEMA = "px.encoding-integrity/1.0"
BOM = b"\xef\xbb\xbf"

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".venv-certify",
    "node_modules",
    "__pycache__",
    ".tmp",
    ".px",
    ".pacify-x",
    "dist",
    "out",
}

SCAN_SUFFIXES = {
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".ps1",
    ".psm1",
    ".sh",
    ".cmd",
    ".bat",
    ".md",
    ".txt",
    ".cfg",
    ".ini",
}

MAX_FILE_BYTES = 8 * 1024 * 1024

# Files that intentionally preserve historical bytes. Repairing them would alter evidence, so they
# are allow-listed by exact path rather than skipped by a broad rule.
HISTORICAL_EVIDENCE_ALLOWLIST = (
    "registry/adversarial_reaudit_20260813.json",
    "docs/architecture/reference/graph_baseline_evidence-map.json",
)

# Files that are intentionally invalid because their invalidity is the thing under test. A syntax
# fixture that parsed would no longer test anything, so the parse failure is expected, not a defect.
INTENTIONAL_INVALID_ALLOWLIST = (
    "tests/fixtures/semantic_code/python_project/broken.py",
)

# Bytes >= 0x20 are fine; tab/newline/carriage-return are fine. Everything else in the C0 range is
# not expected in authored text.
ALLOWED_CONTROL = {0x09, 0x0A, 0x0D}


def _iter_files(root: Path):
    areas = (
        "runtime",
        "scripts",
        "tests",
        "extension",
        "bootstrap",
        "policies",
        "contracts",
        "models",
        "docs",
        "registry",
        "orchestration",
        ".px",
    )
    for area in areas:
        base = root / area
        if not base.exists():
            continue
        stack = [base]
        while stack:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir():
                        if entry.name not in EXCLUDE_DIRS:
                            stack.append(entry)
                        continue
                    if (
                        not entry.is_file()
                        or entry.suffix.casefold() not in SCAN_SUFFIXES
                    ):
                        continue
                    if entry.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                yield entry
    for extra in root.glob("*.md"):
        yield extra
    for extra in root.glob("*.toml"):
        yield extra


def _check_bytes(raw: bytes) -> list[str]:
    problems: list[str] = []
    if raw.startswith(BOM):
        problems.append("utf-8-bom")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        problems.append(f"invalid-utf-8@{error.start}")
        return problems
    for index, char in enumerate(text):
        codepoint = ord(char)
        if codepoint < 0x20 and codepoint not in ALLOWED_CONTROL:
            problems.append(f"control-byte-0x{codepoint:02x}@{index}")
            break
    if "\ufffd" in text:
        problems.append("replacement-character")
    return problems


def _check_parse(path: Path, text: str) -> list[str]:
    suffix = path.suffix.casefold()
    problems: list[str] = []
    if suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as error:
            problems.append(f"json-parse-failure:{error.msg[:60]}")
    elif suffix == ".py":
        try:
            ast.parse(text)
        except SyntaxError as error:
            problems.append(
                f"python-ast-failure:line{error.lineno}:{(error.msg or '')[:60]}"
            )
    elif suffix == ".toml":
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            problems.append(f"toml-parse-failure:{str(error)[:60]}")
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore import-not-found
        except ImportError:
            return problems  # no parser available; absence is not a failure
        try:
            yaml.safe_load(text)
        except Exception as error:  # noqa: BLE001 - any YAML failure is a parse failure
            problems.append(f"yaml-parse-failure:{type(error).__name__}")
    return problems


def verify(root: Path) -> dict:
    root = root.resolve(strict=True)
    findings: list[dict] = []
    allowlisted: list[dict] = []
    scanned = 0
    for path in _iter_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        scanned += 1
        problems = _check_bytes(raw)
        if problems:
            record = {"path": relative, "problems": problems}
            if relative in HISTORICAL_EVIDENCE_ALLOWLIST:
                record["classification"] = "historical_evidence_preserved"
                allowlisted.append(record)
            else:
                findings.append(record)
            # A BOM already fails decoding assumptions; skip parse checks for it.
            if "invalid-utf-8@" in " ".join(problems):
                continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        parse_problems = _check_parse(path, text)
        if parse_problems:
            if relative in INTENTIONAL_INVALID_ALLOWLIST:
                allowlisted.append({
                    "path": relative,
                    "problems": parse_problems,
                    "classification": "intentional_invalid_fixture",
                })
            else:
                findings.append({"path": relative, "problems": parse_problems})
    return {
        "schema_version": SCHEMA,
        "valid": not findings,
        "files_scanned": scanned,
        "finding_count": len(findings),
        "findings": findings[:60],
        "allowlisted_historical_evidence": allowlisted,
        "note": (
            "Encoding defects are generated-state defects: a BOM or a parse failure can silently "
            "break JSON or AST consumers. This gate exists because that happened once already."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(args.root)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["valid"] else 1
    print(
        f"encoding integrity: valid={result['valid']} "
        f"files={result['files_scanned']} findings={result['finding_count']}"
    )
    for finding in result["findings"][:40]:
        print(f"  {finding['path']}: {', '.join(finding['problems'])}")
    for record in result["allowlisted_historical_evidence"]:
        print(f"  (preserved) {record['path']}: {', '.join(record['problems'])}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
