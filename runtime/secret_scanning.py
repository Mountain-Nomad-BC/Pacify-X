"""Bounded credential-shape scanning with identity-bound finding reviews."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Iterable

from .repository_scope import is_external_environment_relative


SKIP_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode-test",
    ".venv",
    "PortableGit",
    "Python",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "preserved-extension-installations",
    "preserved-skills",
}
AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
GITHUB_TOKEN = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")
PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN (?P<kind>(?:RSA |EC |OPENSSH )?PRIVATE KEY)-----"
    r"\s+(?P<body>(?:[A-Za-z0-9+/]{16,}={0,2}\s*){4,})"
    r"-----END (?P=kind)-----",
    re.MULTILINE,
)
GENERIC_ASSIGNMENT = re.compile(
    r"(?i)\b(?P<label>api[_-]?key|secret|password|token)[ \t]*[:=][ \t]*"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;}\]]+)"
)
EXPRESSION_PREFIXES = (
    "${",
    "<",
    "...",
    "config.",
    "env.",
    "getenv(",
    "jwt.",
    "os.",
    "process.",
    "re.",
    "self.",
    "settings.",
    "window.",
)
PLACEHOLDER_FRAGMENTS = (
    "changeme",
    "dummy",
    "fake",
    "placeholder",
    "realkeyvalue",
    "replace_me",
    "sample",
    "your_",
)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _obvious_placeholder(value: str) -> bool:
    candidate = value.strip().strip("\"'")
    lowered = candidate.casefold()
    if len(candidate) < 8:
        return True
    if lowered.startswith(EXPRESSION_PREFIXES) or "(" in candidate or ")" in candidate:
        return True
    if any(fragment in lowered for fragment in PLACEHOLDER_FRAGMENTS):
        return True
    if "..." in candidate or candidate.startswith(("{", "[")):
        return True
    if re.fullmatch(r"[A-Za-z_$][A-Za-z_$.]*", candidate):
        if "." in candidate or any(character.isupper() for character in candidate[1:]):
            return True
    if candidate.upper().startswith("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        return True
    if len(set(candidate.casefold())) <= 3:
        return True
    return False


def _finding(
    path: Path, root: Path, kind: str, line: int, text: str
) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    lines = text.splitlines()
    source_line = lines[line - 1] if 0 < line <= len(lines) else ""
    line_sha256 = hashlib.sha256(source_line.encode("utf-8")).hexdigest()
    # The source line is content identity; its current line number is only a
    # locator. This keeps a reviewed synthetic fixture valid across
    # formatting-only movement while still invalidating any content change.
    identity = hashlib.sha256(
        f"{relative}\0{kind}\0{line_sha256}".encode("utf-8")
    ).hexdigest()[:20]
    return {
        "id": identity,
        "file": relative,
        "kind": kind,
        "line": line,
        "line_sha256": line_sha256,
        "value": "[REDACTED]",
    }


def _scan_text(path: Path, root: Path, text: str) -> Iterable[dict[str, object]]:
    for match in PRIVATE_KEY_BLOCK.finditer(text):
        yield _finding(path, root, "private_key", _line(text, match.start()), text)
    for match in AWS_ACCESS_KEY.finditer(text):
        yield _finding(path, root, "aws_access_key", _line(text, match.start()), text)
    for match in GITHUB_TOKEN.finditer(text):
        if not _obvious_placeholder(match.group(0).split("_", 1)[1]):
            yield _finding(path, root, "github_token", _line(text, match.start()), text)
    for match in GENERIC_ASSIGNMENT.finditer(text):
        if not _obvious_placeholder(match.group("value")):
            yield _finding(
                path, root, "generic_secret", _line(text, match.start()), text
            )


def scan_secret_shapes(
    root: Path, *, review_registry: Path | None = None
) -> dict[str, object]:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir() or resolved == Path(resolved.anchor):
        raise ValueError("root must be an explicit non-filesystem-root directory")
    findings: list[dict[str, object]] = []
    files_scanned = 0
    errors: list[dict[str, str]] = []
    source_files: list[Path] = []
    for directory, names, files in os.walk(resolved, topdown=True, followlinks=False):
        relative_directory = Path(directory).relative_to(resolved)
        names[:] = sorted(
            name for name in names
            if name not in SKIP_DIRECTORIES
            and not name.startswith(".venv")
            and not is_external_environment_relative(relative_directory / name)
        )
        source_files.extend(Path(directory) / name for name in sorted(files))
    for path in source_files:
        if path.is_symlink() or not path.is_file():
            continue
        try:
            sample = path.read_bytes()
            if b"\x00" in sample[:65536]:
                continue
            text = sample.decode("utf-8", errors="ignore")
        except OSError as error:
            errors.append(
                {
                    "file": path.relative_to(resolved).as_posix(),
                    "error": type(error).__name__,
                }
            )
            continue
        files_scanned += 1
        findings.extend(_scan_text(path, resolved, text))
    registry_path = review_registry or (
        resolved / "registry/secret_finding_reviews.json"
    )
    reviews: dict[str, dict[str, object]] = {}
    if registry_path.is_file():
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            reviews = {str(item["id"]): item for item in payload.get("records", ())}
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            errors.append({"file": str(registry_path), "error": type(error).__name__})
    finding_ids = {str(item["id"]) for item in findings}
    for item in findings:
        review = reviews.get(str(item["id"]))
        if review and all(
            review.get(key) == item.get(key) for key in ("file", "kind", "line_sha256")
        ):
            item["classification"] = str(
                review.get("classification", "reviewed_fixture")
            )
            item["review_owner"] = str(review.get("owner", "unknown"))
        else:
            item["classification"] = "unreviewed"
    stale_reviews = sorted(set(reviews) - finding_ids)
    if stale_reviews:
        errors.append({"file": str(registry_path), "error": "stale_reviews"})
    unreviewed = [item for item in findings if item["classification"] == "unreviewed"]
    return {
        "schema_version": "1.1",
        "scan_scope": "active-source-tree; generated custody, caches, environments, build outputs, and dependency stores excluded",
        "valid": not unreviewed and not errors,
        "files_scanned": files_scanned,
        "finding_count": len(findings),
        "reviewed_count": len(findings) - len(unreviewed),
        "unreviewed_count": len(unreviewed),
        "findings": findings,
        "error_count": len(errors),
        "errors": errors,
    }
