"""Map every staged external requirement file to a canonical local owner.

Input is the sanitized behavior index only.  Output is content-addressed and
contains hashes and dispositions, never source bodies or absolute paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tomllib


NEW_OWNERS = {
    "validate-contract-boundaries", "evaluate-retrieval-readiness",
    "gate-model-data-lifecycle",
}

RULE_OWNERS = {
    "00": ("orchestrate-engineering-loop", "enforce-governance-controls"),
    "01": ("orchestrate-engineering-loop", "verify-outcome"),
    "02": ("analyze-engineering-intelligence", "validate-engineering-outcomes"),
    "03": ("validate-engineering-outcomes", "verify-outcome"),
    "04": ("enforce-governance-controls", "validate-contract-boundaries"),
    "05": ("validate-engineering-outcomes",),
    "06": ("analyze-engineering-intelligence", "validate-engineering-outcomes"),
    "07": ("supervise-contained-execution", "discover-environment-safely"),
    "08": ("recovery-coordinator", "govern-memory-fabric"),
    "09": ("discover-environment-safely", "commission-evidence-first-project"),
    "10": ("verify-outcome", "outcome-verifier"),
    "11": ("enforce-governance-controls", "evaluation-budget-allocator"),
    "12": ("dependency-impact-tracer", "validate-contract-boundaries"),
    "13": ("validate-contract-boundaries", "gate-model-data-lifecycle"),
    "14": ("validate-engineering-outcomes", "audit-ai-runtime-assurance"),
    "15": ("enforce-governance-controls", "supervise-contained-execution"),
    "16": ("analyze-engineering-intelligence",),
    "17": ("validate-engineering-outcomes", "certify-skeptical-engineering"),
    "18": ("validate-contract-boundaries", "dependency-impact-tracer"),
    "19": ("orchestrate-engineering-loop", "validate-engineering-outcomes"),
    "20": ("validate-engineering-outcomes",),
    "21": ("validate-engineering-outcomes",),
    "22": ("validate-contract-boundaries",),
    "23": ("validate-contract-boundaries", "enforce-governance-controls"),
    "24": ("validate-contract-boundaries", "enforce-governance-controls"),
    "25": ("validate-engineering-outcomes", "recovery-coordinator"),
    "26": ("verify-outcome", "analyze-engineering-intelligence"),
    "27": ("govern-memory-fabric", "validate-engineering-outcomes"),
    "28": ("propose-change-intelligence", "dependency-impact-tracer"),
    "29": ("validate-engineering-outcomes", "benchmark-domain-adapter"),
    "30": ("recovery-coordinator", "verify-outcome"),
    "31": ("admit-capability", "analyze-engineering-intelligence"),
    "32": ("validate-contract-boundaries", "analyze-engineering-intelligence"),
    "33": ("analyze-engineering-intelligence", "discover-environment-safely"),
    "34": ("enforce-governance-controls",),
    "35": ("supervise-contained-execution", "enforce-governance-controls"),
    "36": ("validate-engineering-outcomes", "evaluate-retrieval-readiness"),
}

SKILL_OWNERS = {
    "api-contract-validator": ("validate-contract-boundaries",),
    "docker-lifecycle": ("validate-engineering-outcomes", "supervise-contained-execution"),
    "self-healing-dev-loop": ("diagnose-python-repair", "recovery-coordinator"),
    "system-validation": ("validate-engineering-outcomes", "orchestrate-engineering-loop"),
    "architecture-review": ("analyze-engineering-intelligence",),
    "production-readiness": ("validate-engineering-outcomes",),
    "slow-thinking": ("orchestrate-engineering-loop",),
    "diagnostic-logic-explainer": ("analyze-engineering-intelligence", "validate-engineering-outcomes"),
    "diagnostic-system-interpreter": ("analyze-engineering-intelligence",),
    "engineering-context": ("forge-skills-from-knowledge",),
    "units-checker": ("validate-engineering-outcomes",),
    "context-assembler": ("govern-memory-fabric",),
    "domain-knowledge-loader": ("forge-skills-from-knowledge",),
    "embedding-optimizer": ("evaluate-retrieval-readiness", "audit-ai-runtime-assurance"),
    "knowledge-graph-builder": ("govern-memory-fabric", "analyze-engineering-intelligence"),
    "rag-aware-codex": ("govern-memory-fabric", "orchestrate-engineering-loop"),
    "rag-builder": ("evaluate-retrieval-readiness", "forge-skills-from-knowledge"),
    "rag-performance-analyzer": ("evaluate-retrieval-readiness",),
    "rag-self-healing": ("evaluate-retrieval-readiness", "recovery-coordinator"),
    "governed-runtime-activation-gate": ("evaluate-retrieval-readiness",),
    "governed-runtime-query-bridge": ("evaluate-retrieval-readiness", "enforce-governance-controls"),
    "retrieval-quality-tester": ("evaluate-retrieval-readiness",),
    "semantic-cluster-mapper": ("analyze-engineering-intelligence", "forge-skills-from-knowledge"),
    "smart-chunker": ("evaluate-retrieval-readiness",),
    "code-quality-enforcer": ("validate-engineering-outcomes",),
    "completion-enforcer": ("verify-outcome",),
    "migration-planner": ("dependency-impact-tracer", "propose-change-intelligence"),
    "repo-doctor": ("analyze-engineering-intelligence",),
    "architecture-mapper": ("analyze-engineering-intelligence",),
    "calculation-graph": ("validate-engineering-outcomes", "forge-skills-from-knowledge"),
    "dependency-graph-builder": ("analyze-engineering-intelligence", "dependency-impact-tracer"),
    "pipeline-interpreter": ("analyze-engineering-intelligence",),
    "system-overview-loader": ("discover-environment-safely",),
    "system-state-inspector": ("validate-engineering-outcomes",),
    "autonomous-ui-auditor": ("validate-engineering-outcomes",),
    "ui-behavior-tests": ("validate-engineering-outcomes",),
    "ui-explorer": ("validate-engineering-outcomes", "discover-environment-safely"),
    "ui-failure-analyzer": ("validate-engineering-outcomes", "analyze-engineering-intelligence"),
}


def _catalog_ids(path: Path) -> set[str]:
    with path.open("rb") as stream:
        return {str(item["id"]) for item in tomllib.load(stream).get("skills", ())}


def _records(path: Path) -> list[dict[str, object]]:
    values = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record.get("source_alias") == "source-12":
                values.append(record)
    return values


def build(index_path: Path, catalog_path: Path) -> dict[str, object]:
    catalog = _catalog_ids(catalog_path)
    source = sorted(_records(index_path), key=lambda item: str(item["relative_path"]).casefold())
    cards = []
    for sequence, record in enumerate(source, 1):
        relative = str(record["relative_path"])
        stem = Path(relative).parent.name if Path(relative).name.casefold() == "skill.md" else Path(relative).stem[:2]
        if relative.casefold().startswith("persistant_rules/"):
            owners = RULE_OWNERS.get(stem, ())
            kind = "persistent_rule"
        else:
            owners = SKILL_OWNERS.get(stem, ())
            kind = "staged_skill"
        missing = sorted(set(owners) - catalog)
        if not owners:
            disposition = "blocked_unmapped"
        elif missing:
            disposition = "blocked_missing_owner"
        elif stem == "engineering-context":
            disposition = "reference_only_domain_knowledge"
        elif set(owners) & NEW_OWNERS:
            disposition = "integrated_clean_room_owner"
        else:
            disposition = "integrated_existing_owner"
        cards.append({
            "card_id": f"EXT-S12-{sequence:03d}", "source_alias": "source-12",
            "relative_path": relative, "sha256": record["sha256"], "kind": kind,
            "disposition": disposition, "canonical_owners": list(owners),
            "missing_owners": missing, "source_body_copied": False,
            "validation": "complete" if disposition.startswith(("integrated", "reference_only")) else "blocked",
            "original_mutated": False,
        })
    payload = {
        "schema_version": "1.0", "source_alias": "source-12",
        "source_file_count": len(source), "card_count": len(cards),
        "complete": bool(cards) and all(card["validation"] == "complete" for card in cards),
        "direct_copy": False, "originals_mutated": False,
        "cards": cards,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**payload, "disposition_sha256": digest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    payload = build(args.index.resolve(), args.catalog.resolve())
    destination = args.output_root.resolve() / str(payload["disposition_sha256"])
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "source-12-disposition.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"output": destination.as_posix(), "count": payload["card_count"], "complete": payload["complete"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
