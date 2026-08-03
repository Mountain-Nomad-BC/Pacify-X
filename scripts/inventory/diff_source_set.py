"""Build a deterministic content diff for a source set against the rest of a workspace."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re


TEXT_SUFFIXES = {
    ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".csv", ".mmd",
    ".toml", ".py", ".ps1", ".sh", ".js", ".ts", ".tsx", ".html", ".css",
}
SKIP_NAMES = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_hash(path: Path) -> str | None:
    if path.suffix.casefold() not in TEXT_SUFFIXES:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def files_under(root: Path, *, excluded_roots: tuple[Path, ...] = ()):
    excluded = tuple(path.resolve() for path in excluded_roots)
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or any(part in SKIP_NAMES for part in path.relative_to(root).parts):
            continue
        resolved = path.resolve()
        if any(resolved == item or item in resolved.parents for item in excluded):
            continue
        yield path


def scope(relative: str, target_name: str) -> str:
    parts = Path(relative).parts
    if not parts:
        return "unknown"
    if parts[0] == target_name:
        if len(parts) > 1 and parts[1] in {
            "runtime", "builders", "contracts", "registry", "orchestration", "bootstrap",
            "tests", ".agents", "policies", "integrations", "models", "knowledge",
        }:
            return "active_implementation"
        if len(parts) > 2 and parts[1:3] == ("planning", "inventory"):
            return "generated_inventory"
        return "active_documentation_or_evidence"
    if parts[0] == "temp" and len(parts) > 1 and parts[1] == "quarantine":
        return "quarantine"
    return "staged_reference"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    source = args.source.resolve()
    source.relative_to(workspace)
    quarantine = workspace / "temp" / "quarantine"

    source_files = list(files_under(source))
    sizes = {path.stat().st_size for path in source_files}
    other_by_size: dict[int, list[Path]] = defaultdict(list)
    for path in files_under(workspace, excluded_roots=(source, quarantine)):
        size = path.stat().st_size
        if size in sizes:
            other_by_size[size].append(path)

    other_hash_cache: dict[Path, tuple[str, str | None]] = {}
    records: list[dict[str, object]] = []
    for path in source_files:
        size = path.stat().st_size
        digest = sha256_file(path)
        normalized = normalized_hash(path)
        exact_matches: list[dict[str, str]] = []
        normalized_matches: list[dict[str, str]] = []
        for candidate in other_by_size.get(size, ()):
            hashes = other_hash_cache.get(candidate)
            if hashes is None:
                hashes = (sha256_file(candidate), normalized_hash(candidate))
                other_hash_cache[candidate] = hashes
            relative = candidate.relative_to(workspace).as_posix()
            match = {"path": relative, "scope": scope(relative, args.target_name)}
            if hashes[0] == digest:
                exact_matches.append(match)
            elif normalized and hashes[1] == normalized:
                normalized_matches.append(match)
        exact_matches.sort(key=lambda item: (item["scope"], item["path"]))
        normalized_matches.sort(key=lambda item: (item["scope"], item["path"]))
        records.append({
            "source_path": path.relative_to(source).as_posix(),
            "extension": path.suffix.casefold(),
            "bytes": size,
            "sha256": digest,
            "normalized_sha256": normalized,
            "exact_matches": exact_matches,
            "normalized_matches": normalized_matches,
            "exact_active_implementation": any(item["scope"] == "active_implementation" for item in exact_matches),
            "exact_anywhere": bool(exact_matches),
        })

    records.sort(key=lambda item: str(item["source_path"]).casefold())
    counts = Counter()
    for record in records:
        counts["source_files"] += 1
        counts["exact_anywhere"] += int(bool(record["exact_anywhere"]))
        counts["exact_active_implementation"] += int(bool(record["exact_active_implementation"]))
        counts["no_exact_match"] += int(not bool(record["exact_anywhere"]))
        counts["markdown"] += int(record["extension"] == ".md")
    output = {
        "schema_version": "1.0",
        "source": source.relative_to(workspace).as_posix(),
        "target": args.target_name,
        "summary": dict(sorted(counts.items())),
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
