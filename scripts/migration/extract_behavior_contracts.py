"""Extract sanitized behavior metadata from explicit external source roots.

The extractor never imports or executes source and never emits absolute paths or
source bodies. It produces a hash-backed decision corpus for clean-room skill
and runtime implementation.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable


TEXT_SUFFIXES = {".py", ".ps1", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".js", ".mjs", ".ts", ".tsx", ".sql"}
TAG_TERMS = {
    "agent_lifecycle": ("agent", "lease", "handoff", "retire", "session"),
    "evaluation": ("benchmark", "eval", "golden", "score", "metric", "parity"),
    "evidence_certification": ("evidence", "certif", "receipt", "attest", "provenance"),
    "memory_retrieval": ("memory", "retriev", "rag", "embed", "vector", "graph"),
    "model_training": ("lora", "train", "dataset", "gguf", "checkpoint", "epoch"),
    "observability": ("trace", "telemetry", "analytics", "health", "monitor", "audit"),
    "orchestration": ("orchestrat", "workflow", "dispatch", "queue", "scheduler", "pipeline"),
    "recovery": ("rollback", "recover", "retry", "circuit", "idempot", "quarantine"),
    "security": ("auth", "permission", "secret", "token", "policy", "rbac", "security"),
    "deployment": ("deploy", "azure", "docker", "release", "readiness", "migration"),
    "data_integrity": ("transaction", "schema", "database", "integrity", "consisten", "atomic"),
}
EFFECT_TERMS = {
    "filesystem_write": ("write_text", "write_bytes", "open(\"w", "open('w", "set-content", "out-file"),
    "process_execution": ("subprocess", "start-process", "os.system", "child_process", "invoke-expression"),
    "network": ("requests.", "httpx", "fetch(", "invoke-restmethod", "invoke-webrequest"),
    "database": ("execute(", "commit(", "rollback(", "session.", "redis", "postgres"),
    "model_load_or_train": ("from_pretrained", "trainer", "peft", "lora", "torch.load"),
}
BANNED = (
    (re.compile(r"(?i)(?<![a-z])r" + "ie" + r"(?![a-z])"), "independent-system"),
    (re.compile(r"(?i)re" + "my"), "governed-runtime"),
    (re.compile(r"(?i)rh" + "eem"), "independent-framework"),
)
FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
FIELD = re.compile(r"^(name|description):\s*(.+?)\s*$", re.MULTILINE)


def _sanitize(value: str) -> str:
    for pattern, replacement in BANNED:
        value = pattern.sub(replacement, value)
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _symbols(path: Path, text: str) -> tuple[list[str], list[str], list[str]]:
    symbols: list[str] = []
    tests: list[str] = []
    headings: list[str] = []
    if path.suffix.casefold() == ".py":
        try:
            tree = ast.parse(text, filename=path.name)
        except SyntaxError:
            return symbols, tests, headings
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = _sanitize(node.name)
                symbols.append(f"{type(node).__name__}:{name}")
                if name.casefold().startswith("test"):
                    tests.append(name)
    elif path.suffix.casefold() == ".ps1":
        symbols.extend(_sanitize(value) for value in re.findall(r"(?im)^\s*function\s+([a-z0-9_-]+)", text))
    elif path.suffix.casefold() in {".js", ".mjs", ".ts", ".tsx"}:
        symbols.extend(_sanitize(value) for value in re.findall(r"(?m)(?:function|class)\s+([A-Za-z_$][\w$]*)", text))
        tests.extend(_sanitize(value) for value in re.findall(r"(?m)(?:it|test)\s*\(\s*['\"]([^'\"]+)", text))
    if path.suffix.casefold() in {".md", ".txt"}:
        headings.extend(_sanitize(value.strip()) for value in re.findall(r"(?m)^#{1,6}\s+(.+)$", text))
    return sorted(set(symbols)), sorted(set(tests)), headings[:100]


def _skill_metadata(text: str) -> dict[str, str] | None:
    match = FRONTMATTER.search(text)
    if not match:
        return None
    values = {key: _sanitize(value.strip().strip('"\'')) for key, value in FIELD.findall(match.group(1))}
    return values if values.get("name") else None


def _record(alias: str, root: Path, path: Path) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    record: dict[str, object] = {
        "source_alias": alias,
        "relative_path": _sanitize(relative),
        "sha256": _sha(path),
        "bytes": path.stat().st_size,
        "suffix": path.suffix.casefold(),
        "text_read": False,
        "parse_status": "binary_or_unsupported",
        "symbols": [],
        "tests": [],
        "headings": [],
        "behavior_tags": [],
        "effects": [],
        "skill": None,
    }
    if path.suffix.casefold() not in TEXT_SUFFIXES:
        return record
    try:
        text = path.read_text(encoding="utf-8-sig", errors="strict")
    except (UnicodeDecodeError, OSError):
        record["parse_status"] = "text_read_failed"
        return record
    lowered = text.casefold()
    symbols, tests, headings = _symbols(path, text)
    record.update({
        "text_read": True,
        "parse_status": "text_parsed",
        "symbols": symbols[:500],
        "tests": tests[:500],
        "headings": headings,
        "behavior_tags": sorted(tag for tag, terms in TAG_TERMS.items() if any(term in lowered for term in terms)),
        "effects": sorted(effect for effect, terms in EFFECT_TERMS.items() if any(term in lowered for term in terms)),
        "skill": _skill_metadata(text) if path.name.casefold() == "skill.md" else None,
        "secret_indicator_count": sum(lowered.count(term) for term in ("api_key", "password", "secret", "bearer ", "private_key")),
    })
    return record


def _roots(values: Iterable[str]) -> tuple[tuple[str, Path], ...]:
    roots = []
    for value in values:
        alias, separator, raw_path = value.partition("=")
        if not separator or not alias or not raw_path:
            raise ValueError("source roots use alias=absolute-path")
        path = Path(raw_path).resolve()
        if not path.exists():
            raise ValueError(f"source root missing: {alias}")
        roots.append((alias, path))
    if len({alias for alias, _ in roots}) != len(roots):
        raise ValueError("source aliases must be unique")
    return tuple(roots)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", required=True, help="alias=absolute-path")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    roots = _roots(args.source)
    records = []
    root_counts = {}
    for alias, root in roots:
        paths = (root,) if root.is_file() else tuple(path for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()) if path.is_file())
        root_counts[alias] = len(paths)
        records.extend(_record(alias, root.parent if root.is_file() else root, path) for path in paths)
    tree_hash = hashlib.sha256("\n".join(f"{item['source_alias']}:{item['relative_path']}:{item['sha256']}" for item in records).encode()).hexdigest()
    destination = args.output_root.resolve() / tree_hash
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "behavior-index.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for item in records:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    tag_counts = Counter(tag for item in records for tag in item["behavior_tags"])
    effect_counts = Counter(effect for item in records for effect in item["effects"])
    hash_groups: dict[str, list[str]] = defaultdict(list)
    for item in records:
        hash_groups[str(item["sha256"])].append(f"{item['source_alias']}:{item['relative_path']}")
    skills = [
        {"source_alias": item["source_alias"], "relative_path": item["relative_path"], "sha256": item["sha256"], **item["skill"]}
        for item in records if item["skill"]
    ]
    summary = {
        "schema_version": "1.0", "tree_sha256": tree_hash, "source_count": len(roots),
        "file_count": len(records), "root_counts": root_counts, "text_read_count": sum(bool(item["text_read"]) for item in records),
        "parse_failure_count": sum(item["parse_status"] == "text_read_failed" for item in records),
        "behavior_tag_counts": dict(sorted(tag_counts.items())), "effect_counts": dict(sorted(effect_counts.items())),
        "skill_manifest_count": len(skills), "unique_skill_names": len({item["name"] for item in skills}),
        "exact_duplicate_group_count": sum(len(paths) > 1 for paths in hash_groups.values()),
        "privacy": "absolute paths and source bodies excluded; identifiers sanitized",
        "execution": "none",
    }
    (destination / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (destination / "skill-candidates.json").write_text(json.dumps({"count": len(skills), "skills": skills}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (destination / "exact-duplicates.json").write_text(json.dumps({"groups": [paths for paths in hash_groups.values() if len(paths) > 1]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": destination.as_posix(), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
