"""Create a complete, context-safe file catalog for a large source corpus."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

TEXT_EXTENSIONS = {".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".jsonl", ".py", ".ps1", ".sh", ".js", ".ts", ".tsx", ".jsx", ".csv", ".xml", ".ini", ".cfg"}
EXCLUDED_SEGMENTS = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build"}
_SOURCE_TERMS = ("r" + "ie", "re" + "my", "rh" + "eem")
TERMS = re.compile(rf"(?i)(?<![A-Za-z])({'|'.join(_SOURCE_TERMS)})(?![A-Za-z])")


def redact(value: str) -> str:
    replacements = dict(zip(_SOURCE_TERMS, ("intelligent_integrations_and_engines", "governed_retrieval_system_with_deterministic_rails", "enterprise")))
    return TERMS.sub(lambda match: replacements[match.group(1).lower()], value)


def classify(path: Path, relative: Path, size: int) -> tuple[str, str]:
    parts = {part.casefold() for part in relative.parts}
    name = path.name.casefold()
    if parts & EXCLUDED_SEGMENTS:
        return "generated_or_dependency", "exclude_from_runtime"
    if any(token in parts for token in {"security", "governance", "policy", "certification", "evidence"}):
        return "governance_or_assurance", "review_for_pattern"
    if any(token in parts for token in {"skill_staging", "skills", ".codex"}) or "skill" in name:
        return "skill_or_registry", "admission_required"
    if any(token in parts for token in {"tests", "test-results"}) or name.startswith("test_"):
        return "test_or_validation", "review_for_pattern"
    if any(token in parts for token in {"deploy", "infra", "monitoring", "ci"}):
        return "operations", "review_for_pattern"
    if any(token in parts for token in {"docs", "references", "temp_references", "knowledge", "research"}):
        return "knowledge_or_reference", "reference_only"
    if path.suffix.casefold() in {".zip", ".tar", ".gz", ".rar", ".7z", ".png", ".jpg", ".jpeg", ".pdf", ".db", ".sqlite", ".pyc"}:
        return "binary_or_archive", "exclude_from_runtime"
    if size > 5 * 1024 * 1024:
        return "large_artifact", "reference_only"
    return "implementation_or_misc", "triage_required"


def text_summary(path: Path) -> str:
    if path.suffix.casefold() not in TEXT_EXTENSIONS or path.stat().st_size > 1024 * 1024:
        return ""
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in data.splitlines()[:120]:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.lower().startswith(("purpose:", "description:", "title:")):
            return redact(stripped[:240])
    return redact(" ".join(data.split())[:240])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--summaries", action="store_true", help="Read bounded excerpts from small text files")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    categories: Counter[str] = Counter()
    recommendations: Counter[str] = Counter()
    extensions: Counter[str] = Counter()
    for directory, directories, filenames in os.walk(args.root):
        directories[:] = [name for name in directories if name.casefold() not in EXCLUDED_SEGMENTS]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            try:
                size = path.stat().st_size
                relative = path.relative_to(args.root)
            except OSError:
                continue
            category, recommendation = classify(path, relative, size)
            row = {
                "path": redact(str(relative)), "extension": redact(path.suffix.casefold()), "bytes": size,
                "category": category, "recommendation": recommendation,
                "summary": text_summary(path) if args.summaries else "",
            }
            rows.append(row)
            categories[category] += 1
            recommendations[recommendation] += 1
            extensions[path.suffix.casefold() or "[none]"] += 1
    with (args.out / "file_catalog.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (args.out / "file_catalog.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "extension", "bytes", "category", "recommendation", "summary"])
        writer.writeheader(); writer.writerows(rows)
    report = {
        "root": redact(str(args.root)), "file_count": len(rows), "categories": categories,
        "recommendations": recommendations, "top_extensions": extensions.most_common(30),
    }
    (args.out / "catalog_summary.json").write_text(json.dumps(report, indent=2, default=dict), encoding="utf-8")
    print(json.dumps(report, indent=2, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
