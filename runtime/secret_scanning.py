"""Bounded credential-shape scanning with identity-bound finding reviews."""

from __future__ import annotations

import hashlib
import json
import time
import unicodedata
from pathlib import Path
import re
from typing import Iterable

from .repository_scope import is_external_environment_relative
from .archive_io import reject_path_links
from .bounded_walk import bounded_walk, WalkLimits
from .input_files import (
    contained_file,
    read_file_image,
    relative_source_path,
    check_deadline,
)
from .json_io import decode_json_object, bounded_json_text
from .numeric_inputs import bounded_integer, bounded_text, bounded_sequence


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


# Prepared replacement tail; source application requires the PC24 admission.
MAX_FILES = 30000
MAX_ENTRIES = 60000
MAX_DIRECTORIES = 30000
MAX_DEPTH = 80
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_CORPUS_BYTES = 2 * 1024**3
MAX_CONTROL_BYTES = 1024 * 1024
MAX_LINES = 100000
MAX_MATCHES = 100000
MAX_FINDINGS = 10000
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_CUSTODY = {"quarantine", "repo_quarantine", ".quarantine", "_quarantine"}
_MARKER = re.compile(
    r"-----(?P<direction>BEGIN|END) (?P<kind>(?:RSA |EC |OPENSSH )?PRIVATE KEY)-----"
)
_LINE_BREAK = re.compile(r"\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")
_BODY_TOKEN = re.compile(r"([A-Za-z0-9+/]+)(={0,2})")
_REVIEW_KINDS = {"private_key", "aws_access_key", "github_token", "generic_secret"}
_REVIEW_CLASSES = {
    "test_fixture",
    "detector_fixture",
    "reviewed_code_expression",
    "unreviewed",
}
SCAN_EXCLUSIONS = "Product source only; dependency stores, generated custody/cache trees, mutable runtime projections and quarantine names excluded before descent or body acquisition."
_EXCLUDED_PARTS = (
    frozenset(name.casefold() for name in SKIP_DIRECTORIES) | _CUSTODY | {".mypy_cache"}
)


def _scan_root(root: Path) -> Path:
    if not isinstance(root, Path):
        raise ValueError("scan root must be a Path")
    bounded_text(str(root), "scan root", maximum=4096, strip=False)
    absolute = root.absolute()
    bounded_text(str(absolute), "absolute scan root", maximum=4096, strip=False)
    if any(p.casefold() in _CUSTODY or p == ".." for p in absolute.parts):
        raise ValueError("scan root is excluded or ambiguous")
    reject_path_links(root)
    if absolute == Path(absolute.anchor) or not absolute.is_dir():
        raise ValueError("scan root must be an explicit non-filesystem-root directory")
    return absolute


def _scan_excluded(relative: str) -> bool:
    parts = relative.split("/")
    return (
        is_external_environment_relative(relative)
        or is_external_environment_relative(relative.casefold())
        or relative.casefold() == "registry/operational_gap_ledger.deltas"
        or relative.casefold().startswith("registry/operational_gap_ledger.deltas/")
        or any(
            part.casefold() in _EXCLUDED_PARTS or part.casefold().startswith(".venv")
            for part in parts
        )
    )


class _SourceCorpus:
    """Preflight one source set; retain only the two small control images."""

    def __init__(self, root: Path, *, max_bytes: int = MAX_CORPUS_BYTES):
        self.deadline = time.monotonic() + 60.0
        self.root = _scan_root(root)
        bounded_integer(max_bytes, "corpus byte limit", maximum=MAX_CORPUS_BYTES)
        walked = bounded_walk(
            self.root,
            limits=WalkLimits(
                max_files=MAX_FILES,
                max_depth=MAX_DEPTH,
                max_bytes=max_bytes,
                max_entries=MAX_ENTRIES,
                max_directories=MAX_DIRECTORIES,
                max_duration_seconds=max(0.001, self.deadline - time.monotonic()),
            ),
            exclude=_scan_excluded,
        )
        self.sources = {}
        self.controls = {}
        self.consumed = False
        aliases = set()
        used = 0
        for entry in walked.files:
            check_deadline(self.deadline)
            relative_source_path(entry.relative)
            alias = unicodedata.normalize("NFC", entry.relative).casefold()
            if alias in aliases:
                raise ValueError("ambiguous scan source identity")
            aliases.add(alias)
            path, info = contained_file(self.root, entry.relative)
            if info.st_size != entry.size or info.st_size > MAX_SOURCE_BYTES:
                raise ValueError(
                    "scan source changed or exceeded image limit before acquisition"
                )
            used += info.st_size
            if used > max_bytes:
                raise ValueError("scan aggregate image limit exceeded")
            self.sources[entry.relative] = (path, info)
        check_deadline(self.deadline)

    def control(self, relative: str) -> bytes:
        relative_source_path(relative)
        if relative not in self.sources:
            raise ValueError("required control is absent from the admitted corpus")
        if relative not in self.controls:
            if len(self.controls) >= 2:
                raise ValueError("control image count exceeded")
            path, info = self.sources[relative]
            self.controls[relative] = bytes(
                read_file_image(
                    path, info, limit=MAX_CONTROL_BYTES, deadline=self.deadline
                )
            )
        return self.controls[relative]

    def images(self):
        if self.consumed:
            raise ValueError("source corpus already consumed")
        self.consumed = True
        for relative, (path, info) in self.sources.items():
            check_deadline(self.deadline)
            raw = self.controls.pop(relative, None)
            if raw is None:
                raw = bytes(
                    read_file_image(
                        path, info, limit=MAX_SOURCE_BYTES, deadline=self.deadline
                    )
                )
            yield relative, path, raw


class _ScanBudget:
    def __init__(self, deadline: float):
        self.deadline = deadline
        self.matches = 0
        self.findings = 0
        self.output_bytes = 2

    def match(self):
        check_deadline(self.deadline)
        self.matches += 1
        if self.matches > MAX_MATCHES:
            raise ValueError("scan match work limit exceeded")

    def finding(self, record):
        self.findings += 1
        self.output_bytes += (
            len(json.dumps(record, ensure_ascii=False).encode("utf-8")) + 2
        )
        if self.findings > MAX_FINDINGS or self.output_bytes > MAX_OUTPUT_BYTES:
            raise ValueError("scan finding output limit exceeded")


def _private_blocks(text: str, budget: _ScanBudget):
    opened = None
    for marker in _MARKER.finditer(text):
        budget.match()
        if marker["direction"] == "BEGIN":
            opened = marker
            continue
        if opened is not None and opened["kind"] == marker["kind"]:
            body = text[opened.end() : marker.start()]
            groups = 0
            valid = bool(body) and body[0].isspace()
            for token in re.finditer(r"\S+", body):
                budget.match()
                value = token.group(0)
                position = 0
                for segment in _BODY_TOKEN.finditer(value):
                    budget.match()
                    if segment.start() != position or len(segment[1]) < 16:
                        valid = False
                        break
                    groups += len(segment[1]) // 16
                    position = segment.end()
                if position != len(value):
                    valid = False
                if not valid:
                    break
            if valid and groups >= 4:
                yield opened.start()
        opened = None


def _scan_text(
    path: Path, root: Path, text: str, *, budget=None
) -> Iterable[dict[str, object]]:
    budget = budget or _ScanBudget(time.monotonic() + 60.0)
    spans = []
    position = 0
    for separator in _LINE_BREAK.finditer(text):
        if len(spans) >= MAX_LINES:
            raise ValueError("scan line index limit exceeded")
        spans.append((position, separator.start()))
        position = separator.end()
    if position < len(text):
        if len(spans) >= MAX_LINES:
            raise ValueError("scan line index limit exceeded")
        spans.append((position, len(text)))
    relative = path.relative_to(root).as_posix()
    cursors = {}
    line_hashes = {}

    def finding(kind, offset):
        previous, line = cursors.get(kind, (0, 1))
        line += text.count("\n", previous, offset)
        cursors[kind] = (offset, line)
        if line not in line_hashes:
            source_line = (
                text[slice(*spans[line - 1])] if 0 < line <= len(spans) else ""
            )
            line_hashes[line] = hashlib.sha256(source_line.encode("utf-8")).hexdigest()
        line_sha = line_hashes[line]
        identity = hashlib.sha256(
            f"{relative}\0{kind}\0{line_sha}".encode("utf-8")
        ).hexdigest()[:20]
        record = {
            "id": identity,
            "file": relative,
            "kind": kind,
            "line": line,
            "line_sha256": line_sha,
            "value": "[REDACTED]",
        }
        budget.finding(record)
        return record

    for offset in _private_blocks(text, budget):
        yield finding("private_key", offset)
    for kind, pattern in [
        ("aws_access_key", AWS_ACCESS_KEY),
        ("github_token", GITHUB_TOKEN),
        ("generic_secret", GENERIC_ASSIGNMENT),
    ]:
        for match in pattern.finditer(text):
            budget.match()
            value = (
                match.group("value")
                if kind == "generic_secret"
                else match.group(0).split("_", 1)[1]
                if kind == "github_token"
                else None
            )
            if value is None or not _obvious_placeholder(value):
                yield finding(kind, match.start())
    check_deadline(budget.deadline)


def _reviews(corpus: _SourceCorpus, registry_path: Path | None):
    default = "registry/secret_finding_reviews.json"
    if registry_path is None:
        if default not in corpus.sources:
            return {}, None
        raw = corpus.control(default)
    else:
        if not isinstance(registry_path, Path):
            raise ValueError("review registry must be a Path")
        bounded_text(
            str(registry_path), "review registry path", maximum=4096, strip=False
        )
        original = registry_path.absolute()
        bounded_text(
            str(original), "absolute review registry path", maximum=4096, strip=False
        )
        if any(p.casefold() in _CUSTODY or p == ".." for p in original.parts):
            raise ValueError("review registry is excluded or ambiguous")
        reject_path_links(registry_path)
        if original.is_relative_to(corpus.root):
            raw = corpus.control(original.relative_to(corpus.root).as_posix())
        else:
            path, info = contained_file(original.parent, original.name)
            raw = bytes(
                read_file_image(
                    path, info, limit=MAX_CONTROL_BYTES, deadline=corpus.deadline
                )
            )
    payload = decode_json_object(
        raw, max_bytes=MAX_CONTROL_BYTES, max_depth=32, max_nodes=100000
    )
    if (
        set(payload) != {"schema_version", "records"}
        or payload["schema_version"] != "1.0"
    ):
        raise ValueError("review registry header is invalid")
    reviews = {}
    required = {"id", "file", "kind", "line", "line_sha256", "classification", "owner"}
    for record in bounded_sequence(payload["records"], "review records", maximum=10000):
        check_deadline(corpus.deadline)
        if (
            type(record) is not dict
            or not required <= set(record)
            or set(record) - required - {"rationale"}
        ):
            raise ValueError("review record fields are invalid")
        for key in required - {"line"}:
            bounded_text(
                record[key],
                "review " + key,
                maximum=4096 if key == "file" else 256,
                strip=False,
            )
        relative_source_path(record["file"])
        if (
            record["kind"] not in _REVIEW_KINDS
            or record["classification"] not in _REVIEW_CLASSES
        ):
            raise ValueError("review kind or classification is unsupported")
        bounded_integer(record["line"], "review line", maximum=2**31 - 1)
        if re.fullmatch(r"[0-9a-f]{64}", record["line_sha256"]) is None:
            raise ValueError("review line identity is invalid")
        expected = hashlib.sha256(
            f"{record['file']}\0{record['kind']}\0{record['line_sha256']}".encode(
                "utf-8"
            )
        ).hexdigest()[:20]
        if record["id"] != expected or record["id"] in reviews:
            raise ValueError("review identity is invalid or duplicated")
        if "rationale" in record:
            bounded_text(
                record["rationale"], "review rationale", maximum=4096, strip=False
            )
        reviews[record["id"]] = record
    return reviews, hashlib.sha256(raw).hexdigest()


def _scan_corpus(corpus: _SourceCorpus, *, review_registry=None, consume=None):
    reviews, review_sha = _reviews(corpus, review_registry)
    findings = []
    records = []
    files_scanned = 0
    budget = _ScanBudget(corpus.deadline)
    for relative, path, raw in corpus.images():
        digest = hashlib.sha256(raw).hexdigest()
        records.append((relative, len(raw), digest))
        if b"\0" not in raw[:65536]:
            text = raw.decode("utf-8", errors="ignore")
            files_scanned += 1
            findings.extend(_scan_text(path, corpus.root, text, budget=budget))
        if consume is not None:
            consume(relative, path, raw, digest)
        check_deadline(corpus.deadline)
    finding_ids = {item["id"] for item in findings}
    for item in findings:
        review = reviews.get(item["id"])
        if review and all(
            review[key] == item[key] for key in ("file", "kind", "line_sha256")
        ):
            item["classification"] = review["classification"]
            item["review_owner"] = review["owner"]
        else:
            item["classification"] = "unreviewed"
    stale = bool(set(reviews) - finding_ids)
    errors = [{"file": "review_registry", "error": "stale_reviews"}] if stale else []
    unreviewed = sum(item["classification"] == "unreviewed" for item in findings)
    result = {
        "schema_version": "1.1",
        "scan_scope": SCAN_EXCLUSIONS,
        "valid": not unreviewed and not errors,
        "complete": True,
        "corpus_sha256": hashlib.sha256(
            json.dumps(records, separators=(",", ":")).encode()
        ).hexdigest(),
        "review_registry_sha256": review_sha,
        "file_count": len(records),
        "files_scanned": files_scanned,
        "finding_count": len(findings),
        "reviewed_count": len(findings) - unreviewed,
        "unreviewed_count": unreviewed,
        "findings": findings,
        "error_count": len(errors),
        "errors": errors,
    }
    bounded_json_text(result, max_bytes=MAX_OUTPUT_BYTES)
    check_deadline(corpus.deadline)
    return result


def _incomplete_scan(error):
    return {
        "schema_version": "1.1",
        "scan_scope": SCAN_EXCLUSIONS,
        "valid": False,
        "complete": False,
        "corpus_sha256": None,
        "review_registry_sha256": None,
        "file_count": None,
        "files_scanned": None,
        "finding_count": None,
        "reviewed_count": None,
        "unreviewed_count": None,
        "findings": [],
        "error_count": 1,
        "errors": [{"file": "admitted_scan_scope", "error": type(error).__name__}],
    }


def scan_secret_shapes(
    root: Path, *, review_registry: Path | None = None
) -> dict[str, object]:
    try:
        return _scan_corpus(_SourceCorpus(root), review_registry=review_registry)
    except (OSError, ValueError) as error:
        return _incomplete_scan(error)
