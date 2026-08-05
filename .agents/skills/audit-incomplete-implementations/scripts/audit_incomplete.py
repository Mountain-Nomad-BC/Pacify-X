#!/usr/bin/env python3
"""Find incomplete implementation signals with deterministic, payload-minimized IDs."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path

EXCLUDES = {
    ".git",
    ".venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "quarantine",
    "__pycache__",
}
TEXT_RULES = {
    "todo-comment": re.compile(r"(?i)\b(?:TODO|FIXME|HACK)\b"),
    "unimplemented-error": re.compile(r"(?i)(?:not\s+implemented|NotImplementedError)"),
    "fabricated-success": re.compile(
        r"(?i)(?:return\s+true\s*;?\s*//.*(?:stub|placeholder)|status\s*[:=]\s*['\"]pass['\"].*(?:stub|placeholder))"
    ),
}


def _finding(rel: str, line: int, rule: str, semantic_source: str) -> dict:
    normalized = " ".join(semantic_source.split())
    finding_id = hashlib.sha256(f"{rel}:{rule}:{normalized}".encode()).hexdigest()[:20]
    return {
        "id": finding_id,
        "path": rel,
        "line": line,
        "rule": rule,
        "classification": "unreviewed",
    }


def _python_findings(path: Path, rel: str, source_hash: str) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    findings: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Pass):
            findings.append(
                _finding(
                    rel,
                    node.lineno,
                    "python-pass",
                    ast.dump(node, include_attributes=False),
                )
            )
        elif (
            isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and getattr(node.exc.func, "id", "") == "NotImplementedError"
        ):
            findings.append(
                _finding(
                    rel,
                    node.lineno,
                    "python-not-implemented",
                    ast.dump(node, include_attributes=False),
                )
            )
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and len(node.body) == 1
        ):
            only = node.body[0]
            if (
                isinstance(only, ast.Expr)
                and isinstance(only.value, ast.Constant)
                and only.value.value is Ellipsis
            ):
                findings.append(
                    _finding(
                        rel,
                        only.lineno,
                        "python-ellipsis-body",
                        ast.dump(node, include_attributes=False),
                    )
                )
    return findings


def audit(
    root: Path, max_bytes: int = 1_000_000, review_registry: Path | None = None
) -> dict:
    findings: list[dict] = []
    errors: list[dict] = []
    scanned = 0
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d.casefold() not in EXCLUDES)
        for name in sorted(files, key=str.casefold):
            path = Path(current, name)
            if (
                path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx"}
                or path.is_symlink()
                or path.stat().st_size > max_bytes
            ):
                continue
            scanned += 1
            rel = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            source_hash = hashlib.sha256(raw).hexdigest()
            try:
                text = raw.decode("utf-8")
                if path.suffix.lower() == ".py":
                    findings.extend(_python_findings(path, rel, source_hash))
                for line_number, line in enumerate(text.splitlines(), 1):
                    for rule, pattern in TEXT_RULES.items():
                        if pattern.search(line):
                            findings.append(_finding(rel, line_number, rule, line))
            except (OSError, UnicodeError, SyntaxError) as exc:
                errors.append({"path": rel, "error": type(exc).__name__})
    unique = {item["id"]: item for item in findings}
    ordered = sorted(
        unique.values(), key=lambda item: (item["path"], item["line"], item["rule"])
    )
    reviews: dict[str, dict] = {}
    review_errors: list[dict] = []
    if review_registry:
        try:
            document = json.loads(review_registry.read_text(encoding="utf-8-sig"))
            for record in document.get("records", []):
                review_id = str(record["id"])
                if review_id in reviews:
                    raise ValueError(f"duplicate review id: {review_id}")
                reviews[review_id] = record
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            ValueError,
        ) as exc:
            review_errors.append(
                {"path": review_registry.as_posix(), "error": type(exc).__name__}
            )
    matched_reviews: set[str] = set()
    allowed = {
        "detector_literal",
        "validation_literal",
        "protocol_contract",
        "expected_control_flow",
        "safe_degradation",
        "test_fixture",
        "documentation",
        "unreachable_dead_code",
        "deferred_feature",
    }
    for finding in ordered:
        review = reviews.get(finding["id"])
        if not review:
            continue
        # A line number is a locator, not part of a finding's semantic identity.
        # Formatters may move an otherwise unchanged finding, so reviews bind to
        # the content-derived ID, path, and rule while the registry line remains
        # useful human-facing metadata.
        if any(review.get(field) != finding[field] for field in ("path", "rule")):
            review_errors.append(
                {"path": finding["path"], "error": "review_identity_mismatch"}
            )
            continue
        classification = str(review.get("classification", ""))
        if (
            classification not in allowed
            or not str(review.get("rationale", "")).strip()
            or not str(review.get("review_condition", "")).strip()
        ):
            review_errors.append({"path": finding["path"], "error": "invalid_review"})
            continue
        finding["classification"] = classification
        finding["review_owner"] = str(review.get("owner", "project"))
        matched_reviews.add(finding["id"])
    stale_reviews = sorted(set(reviews) - matched_reviews)
    if stale_reviews:
        review_errors.append(
            {
                "path": review_registry.as_posix() if review_registry else "",
                "error": "stale_reviews",
                "count": len(stale_reviews),
            }
        )
    reviewed = sum(1 for item in ordered if item["classification"] != "unreviewed")
    unreviewed = len(ordered) - reviewed
    all_errors = errors + review_errors
    return {
        "schema_version": "1.0",
        "scan_complete": not errors,
        "review_complete": unreviewed == 0 and not review_errors,
        "complete": not all_errors and unreviewed == 0,
        "files_scanned": scanned,
        "finding_count": len(ordered),
        "reviewed_count": reviewed,
        "unreviewed_count": unreviewed,
        "findings": ordered,
        "errors": all_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-bytes", type=int, default=1_000_000)
    parser.add_argument("--review-registry", type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve(), args.max_bytes, args.review_registry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"complete": result["complete"], "findings": result["finding_count"]}
        )
    )
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
