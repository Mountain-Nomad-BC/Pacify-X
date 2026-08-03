"""Plan clean-room admission of externally indexed behavior and skill metadata.

The planner consumes only the sanitized metadata emitted by
``extract_behavior_contracts.py``.  It never opens or executes the indexed
source files and never copies their bodies.  Output is content-addressed so a
later intake can be compared without overwriting earlier evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Iterable, Mapping


TOKEN = re.compile(r"[a-z0-9]+")
GENERIC = {
    "a", "an", "and", "assistant", "for", "from", "in", "of", "on",
    "skill", "system", "the", "to", "tool", "with",
}

# Broad, reusable capability families.  These labels are intentionally generic
# and do not reproduce source-specific architecture or terminology.
FAMILIES: dict[str, set[str]] = {
    "admission-and-governance": {
        "admission", "approval", "audit", "authorization", "boundary",
        "contract", "governance", "permission", "policy", "risk", "security",
    },
    "assurance-and-evidence": {
        "benchmark", "certification", "completion", "evidence", "evaluation",
        "parity", "quality", "readiness", "test", "validation", "verifier",
    },
    "knowledge-and-retrieval": {
        "chunk", "context", "embedding", "graph", "knowledge", "memory",
        "retrieval", "search", "semantic", "source",
    },
    "operations-and-recovery": {
        "cache", "container", "deploy", "diagnostic", "health", "incident",
        "monitor", "observability", "recovery", "release", "telemetry",
    },
    "architecture-and-change": {
        "architecture", "change", "code", "dependency", "migration",
        "refactor", "repository", "schema", "state", "topology",
    },
    "model-and-data-lifecycle": {
        "adapter", "corpus", "data", "dataset", "drift", "fine", "lora",
        "model", "training", "tuning",
    },
    "workflow-orchestration": {
        "agent", "automation", "execution", "lifecycle", "loop",
        "orchestration", "pipeline", "planner", "workflow",
    },
    "interface-quality": {
        "accessibility", "browser", "frontend", "interface", "page", "ui",
        "user", "visual",
    },
}


def _tokens(*values: str) -> set[str]:
    return {token for value in values for token in TOKEN.findall(value.casefold()) if token not in GENERIC}


def _stable(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _family(tokens: set[str]) -> tuple[str, float]:
    ranked = sorted(
        ((len(tokens & vocabulary), name) for name, vocabulary in FAMILIES.items()),
        key=lambda item: (-item[0], item[1]),
    )
    score, name = ranked[0]
    return (name if score else "other", score / max(1, len(tokens)))


def _similarity(left: set[str], right: set[str]) -> float:
    return len(left & right) / max(1, len(left | right))


def _catalog(path: Path) -> list[dict[str, object]]:
    with path.open("rb") as stream:
        payload = tomllib.load(stream)
    return [dict(item) for item in payload.get("skills", ())]


def _load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    records = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                records.append(json.loads(line))
    return records


def _catalog_match(
    candidate_tokens: set[str],
    candidate_name: str,
    catalog: Iterable[Mapping[str, object]],
) -> tuple[str | None, float]:
    best_id: str | None = None
    best = 0.0
    normalized = "-".join(TOKEN.findall(candidate_name.casefold()))
    for item in catalog:
        item_id = str(item["id"])
        if normalized == item_id:
            return item_id, 1.0
        score = _similarity(candidate_tokens, _tokens(item_id, " ".join(map(str, item.get("tags", ())))))
        if score > best or (score == best and (best_id is None or item_id < best_id)):
            best_id, best = item_id, score
    return best_id, round(best, 6)


def build_plan(index_dir: Path, catalog_path: Path) -> dict[str, object]:
    summary = _load_json(index_dir / "summary.json")
    skill_payload = _load_json(index_dir / "skill-candidates.json")
    records = _load_jsonl(index_dir / "behavior-index.jsonl")
    catalog = _catalog(catalog_path)

    candidate_rows = []
    family_counts: Counter[str] = Counter()
    disposition_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    seen_hashes: defaultdict[str, list[str]] = defaultdict(list)
    for raw in skill_payload.get("skills", ()):  # type: ignore[union-attr]
        item = dict(raw)
        name = str(item.get("name", ""))
        description = str(item.get("description", ""))
        tokens = _tokens(name, description, str(item.get("relative_path", "")))
        family, family_score = _family(tokens)
        match_id, match_score = _catalog_match(tokens, name, catalog)
        source_alias = str(item.get("source_alias", ""))

        if match_score == 1:
            disposition = "already_covered_exact"
        elif match_score >= 0.5:
            disposition = "review_as_existing_skill_extension"
        elif source_alias == "source-12" and family != "other":
            disposition = "clean_room_contract_candidate"
        else:
            disposition = "reference_metadata_only"

        row = {
            "source_alias": source_alias,
            "relative_path": item.get("relative_path"),
            "sha256": item.get("sha256"),
            "name": name,
            "description": description,
            "family": family,
            "family_score": round(family_score, 6),
            "nearest_catalog_skill": match_id,
            "catalog_similarity": match_score,
            "disposition": disposition,
            "direct_copy_allowed": False,
        }
        candidate_rows.append(row)
        family_counts[family] += 1
        disposition_counts[disposition] += 1
        source_counts[source_alias] += 1
        seen_hashes[str(item.get("sha256", ""))].append(f"{source_alias}:{item.get('relative_path')}")

    source_behavior: dict[str, dict[str, object]] = {}
    for record in records:
        alias = str(record.get("source_alias", ""))
        aggregate = source_behavior.setdefault(alias, {
            "files": 0, "text_read": 0, "bytes": 0,
            "behavior_tags": Counter(), "effects": Counter(),
            "tests": 0, "symbols": 0, "secret_indicators": 0,
        })
        aggregate["files"] = int(aggregate["files"]) + 1
        aggregate["bytes"] = int(aggregate["bytes"]) + int(record.get("bytes", 0))
        aggregate["text_read"] = int(aggregate["text_read"]) + int(bool(record.get("text_read")))
        aggregate["tests"] = int(aggregate["tests"]) + len(record.get("tests", ()))
        aggregate["symbols"] = int(aggregate["symbols"]) + len(record.get("symbols", ()))
        aggregate["secret_indicators"] = int(aggregate["secret_indicators"]) + int(record.get("secret_indicator_count", 0))
        aggregate["behavior_tags"].update(record.get("behavior_tags", ()))
        aggregate["effects"].update(record.get("effects", ()))

    for aggregate in source_behavior.values():
        aggregate["behavior_tags"] = dict(sorted(aggregate["behavior_tags"].items()))
        aggregate["effects"] = dict(sorted(aggregate["effects"].items()))

    staged = [row for row in candidate_rows if row["source_alias"] == "source-12"]
    priority = sorted(
        (row for row in staged if row["disposition"] != "reference_metadata_only"),
        key=lambda row: (
            {"already_covered_exact": 0, "review_as_existing_skill_extension": 1, "clean_room_contract_candidate": 2}.get(str(row["disposition"]), 9),
            -float(row["catalog_similarity"]), str(row["name"]),
        ),
    )

    duplicates = [
        {"sha256": digest, "members": sorted(members)}
        for digest, members in sorted(seen_hashes.items()) if digest and len(members) > 1
    ]
    plan = {
        "schema_version": "1.0",
        "input_tree_sha256": summary["tree_sha256"],
        "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "method": {
            "source_bodies_read": False,
            "source_code_executed": False,
            "direct_copy_allowed": False,
            "catalog_similarity": "Jaccard overlap of normalized metadata tokens",
            "legal_posture": "requirements evidence only; independently author implementation and synthetic tests",
        },
        "counts": {
            "indexed_files": summary["file_count"],
            "candidate_manifests": len(candidate_rows),
            "catalog_skills": len(catalog),
            "candidate_sources": dict(sorted(source_counts.items())),
            "families": dict(sorted(family_counts.items())),
            "dispositions": dict(sorted(disposition_counts.items())),
            "metadata_duplicate_groups": len(duplicates),
        },
        "source_behavior_summary": dict(sorted(source_behavior.items())),
        "priority_staged_candidates": priority,
        "all_skill_candidates": sorted(candidate_rows, key=lambda row: (str(row["source_alias"]), str(row["relative_path"]))),
        "metadata_duplicates": duplicates,
    }
    return {**plan, "plan_sha256": _stable(plan)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    plan = build_plan(args.index_dir.resolve(), args.catalog.resolve())
    output = args.output_root.resolve() / str(plan["plan_sha256"])
    output.mkdir(parents=True, exist_ok=False)
    with (output / "admission-plan.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(plan, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"output": output.as_posix(), "counts": plan["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
