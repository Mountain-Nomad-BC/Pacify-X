"""Build a complete deterministic, sanitized, hash-backed file inventory."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_common import canonical_json, parse_roots, sanitize, sha256_file, simhash64  # noqa: E402

DEFAULT_EXCLUDES = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist",
}
TEXT_SUFFIXES = {
    ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".jsonl", ".py",
    ".ps1", ".sh", ".js", ".ts", ".tsx", ".jsx", ".csv", ".xml", ".ini",
    ".cfg", ".html", ".css", ".sql", ".go", ".java", ".cs", ".cpp", ".h",
}
TOOL_NAMES = ("rg", "git", "python", "pytest", "docker", "npm", "pnpm", "node", "codex", "curl")
DECLARATION_KEYS = ("inputs", "outputs", "effects", "dependencies", "tests", "evidence")
TOKEN = re.compile(r"[a-z0-9_./:-]+")


def _domain(value: str) -> tuple[str, float]:
    lowered = value.casefold()
    rules = (
        ("security", ("security", "auth", "jwt", "secret", "permission", "policy")),
        ("orchestration", ("orchestrat", "workflow", "scheduler", "agent", "lifecycle")),
        ("validation", ("test", "evidence", "validation", "verify", "benchmark")),
        ("retrieval", ("retrieval", "rag", "vector", "embedding", "knowledge")),
        ("infrastructure", ("docker", "deploy", "infra", "kubernetes", "terraform", "ci")),
        ("data", ("database", "schema", "sql", "migration", "dataset")),
        ("engineering", ("python", "typescript", "frontend", "backend", "api", "repair")),
    )
    scores = [(name, sum(token in lowered for token in terms)) for name, terms in rules]
    name, score = max(scores, key=lambda item: (item[1], item[0]))
    return (name, min(0.99, 0.55 + 0.1 * score)) if score else ("general", 0.5)


def _is_text(path: Path, sample: bytes, mime: str | None) -> bool:
    if b"\x00" in sample:
        return False
    if path.suffix.casefold() in TEXT_SUFFIXES or (mime and mime.startswith("text/")):
        return True
    try:
        sample.decode("utf-8")
        return bool(sample)
    except UnicodeDecodeError:
        return False


def _frontmatter(lines: list[str]) -> dict[str, str]:
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:80]:
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", line)
        if match:
            result[sanitize(match.group(1))] = sanitize(match.group(2)[:500])
    return result


def _structure(text: str) -> dict[str, object]:
    clean = sanitize(text)
    lines = clean.splitlines()
    headings = [line.strip()[:500] for line in lines if re.match(r"^#{1,6}\s+\S", line.strip())]
    fences = sorted(set(match.group(1).casefold() or "plain" for match in re.finditer(r"^```\s*([^\s`]*)", clean, re.MULTILINE)))
    links = sorted(set(match.group(2)[:500] for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", clean)))[:200]
    tool_mentions = sorted(name for name in TOOL_NAMES if re.search(rf"(?i)(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", clean))
    commands = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("python ", "pytest ", "git ", "rg ", "docker ", "npm ", "pnpm ", "codex ")):
            commands.append(stripped[:500])
    declarations: dict[str, list[str]] = {key: [] for key in DECLARATION_KEYS}
    for line in lines:
        match = re.match(r"^\s*[-*]?\s*(inputs?|outputs?|effects?|dependencies|tests?|evidence)\s*:\s*(.+)$", line, re.IGNORECASE)
        if match:
            key = match.group(1).casefold().rstrip("s")
            canonical = {"input": "inputs", "output": "outputs", "effect": "effects", "dependencie": "dependencies", "dependenc": "dependencies", "test": "tests", "evidence": "evidence"}.get(key, key + "s")
            if canonical in declarations:
                declarations[canonical].append(match.group(2).strip()[:500])
    normalized = re.sub(r"\s+", " ", clean.casefold()).strip()
    tokens = TOKEN.findall(normalized)[:100000]
    return {
        "headings": headings[:500],
        "frontmatter": _frontmatter(lines),
        "code_languages": fences,
        "commands": sorted(set(commands))[:200],
        "tools": tool_mentions,
        "links": links,
        "declarations": {key: sorted(set(values)) for key, values in declarations.items()},
        "normalized_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "simhash64": simhash64(tokens),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", required=True, help="label=path; repeatable")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--errors", type=Path)
    parser.add_argument("--max-structure-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--root-files-only", action="store_true", help="inventory files directly below each root and skip subdirectories")
    args = parser.parse_args()
    if args.max_structure_bytes < 1:
        raise ValueError("--max-structure-bytes must be positive")
    roots = parse_roots(args.root)
    excludes = DEFAULT_EXCLUDES | {value.casefold() for value in args.exclude}
    records: list[dict] = []
    errors: list[dict] = []
    discovered: Counter[str] = Counter()
    for label, root in roots:
        for directory, directories, filenames in os.walk(root):
            if args.root_files_only:
                directories[:] = []
            directories[:] = sorted(name for name in directories if name.casefold() not in excludes)
            base = Path(directory)
            for filename in sorted(filenames):
                path = base / filename
                discovered[label] += 1
                try:
                    relative = path.relative_to(root).as_posix()
                    stat = path.stat()
                    with path.open("rb") as handle:
                        sample = handle.read(65536)
                    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    text = _is_text(path, sample, mime)
                    structure: dict[str, object] = {}
                    if text and stat.st_size <= args.max_structure_bytes:
                        structure = _structure(path.read_text(encoding="utf-8", errors="replace"))
                    domain, confidence = _domain(relative + " " + " ".join(structure.get("headings", [])))
                    records.append({
                        "id": hashlib.sha256(f"{label}:{relative}".encode()).hexdigest()[:20],
                        "source_tree": label,
                        "path": sanitize(relative),
                        "extension": sanitize(path.suffix.casefold()),
                        "mime": mime,
                        "bytes": stat.st_size,
                        "sha256": sha256_file(path),
                        "content_kind": "text" if text else "binary",
                        "probable_domain": domain,
                        "domain_confidence": confidence,
                        "structure": structure,
                    })
                except (OSError, ValueError) as error:
                    errors.append({"source_tree": label, "path": sanitize(str(path.relative_to(root))), "error": sanitize(f"{type(error).__name__}: {error}")})
    records.sort(key=lambda item: (item["source_tree"], item["path"], item["id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            line = canonical_json(record) + "\n"
            handle.write(line)
            digest.update(line.encode())
    error_path = args.errors or args.output.with_name("file_inventory_errors.jsonl")
    with error_path.open("w", encoding="utf-8", newline="\n") as handle:
        for error in sorted(errors, key=lambda item: (item["source_tree"], item["path"])):
            handle.write(canonical_json(error) + "\n")
    summary = {
        "schema_version": "1.0",
        "record_count": len(records),
        "error_count": len(errors),
        "inventory_sha256": digest.hexdigest(),
        "roots": [
            {"label": label, "files_discovered": discovered[label], "records": sum(item["source_tree"] == label for item in records), "reconciled": discovered[label] == sum(item["source_tree"] == label for item in records) + sum(item["source_tree"] == label for item in errors)}
            for label, _ in roots
        ],
        "content_kinds": dict(sorted(Counter(item["content_kind"] for item in records).items())),
        "domains": dict(sorted(Counter(item["probable_domain"] for item in records).items())),
        "extensions": dict(Counter(item["extension"] or "[none]" for item in records).most_common()),
    }
    summary_path = args.summary or args.output.with_name("file_inventory_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    markdown = args.output.with_name("file_inventory_summary.md")
    markdown.write_text(
        "# File inventory summary\n\n"
        f"- Records: {len(records)}\n- Errors: {len(errors)}\n- Inventory SHA-256: `{digest.hexdigest()}`\n"
        + "".join(f"- {item['label']}: {item['records']} records; reconciled={str(item['reconciled']).lower()}\n" for item in summary["roots"]),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0 if not errors and all(item["reconciled"] for item in summary["roots"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
