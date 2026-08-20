#!/usr/bin/env python3
"""Build a fail-closed reconstruction ledger for manifest-declared absent artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath


ABSENT_PACK_PREFIXES = tuple(f"{index:02d}-" for index in range(1, 8))
PACK_DOMAINS = {
    "01": "governed execution, evidence, permission, recovery, and durable task control",
    "02": "repository mapping, runtime tracing, impact analysis, reproduction, and safe change planning",
    "03": "verification design, adversarial evaluation, regression quality, and trajectory assessment",
    "04": "isolated memory, grounded retrieval, telemetry, replay, retention, and quality drift",
    "05": "security boundaries, sandboxing, authority, supply-chain provenance, and incident response",
    "06": "runtime compatibility, protocol governance, capacity, canary delivery, and safe degradation",
    "07": "completeness, collision handling, revocable certification, recertification, and release trust",
    "registry": "suite-level ownership, integrity, and build metadata",
}


def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "unnamed"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_manifest_path(value: str) -> str:
    return value.removeprefix("manifest:").replace("\\", "/")


def pack_key(pack: str) -> str:
    return pack[:2] if pack[:2].isdigit() else "registry"


def support_identity(row: dict) -> tuple[str, str]:
    path = PurePosixPath(row["path"])
    artifact_type = row["artifact_type"]
    stem = path.name
    for suffix in (".schema.json", ".json", ".yaml", ".yml", ".md", ".py"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    stem = stem.replace("_", "-")
    # These artifacts are pack-specific even when their filenames repeat.
    if artifact_type in {"pack-metadata", "evidence", "test-or-evaluation"}:
        stem = f"pack-{pack_key(row['pack'])}-{stem}"
    elif artifact_type == "registry" and row["pack"] != "registry":
        stem = f"pack-{pack_key(row['pack'])}-{stem}"
    return artifact_type, slug(stem)


def inferred_behavior(kind: str, source_id: str, pack: str) -> str:
    phrase = source_id.replace("-", " ")
    domain = PACK_DOMAINS[pack_key(pack)]
    if kind == "skill":
        return f"Provide a bounded, triggerable procedure for {phrase} within {domain}, including inputs, authority limits, failure handling, recovery, and evidence."
    if kind == "script":
        return f"Provide a deterministic command-line or library operation for {phrase} within {domain}; reject invalid input, emit structured output, and avoid unapproved mutation."
    if kind == "orchestration":
        return f"Coordinate {phrase} across explicit ordered dependencies within {domain}, with preconditions, budgets, failure policy, rollback or compensation, and evidence outputs."
    return f"Supply the {phrase} support artifact required by {domain}, with explicit ownership, consumers, validation, compatibility, and provenance."


def targets(kind: str, source_id: str, owner: str | None) -> list[str]:
    if kind == "skill":
        base = [
            f".px/skills/{owner or source_id}/SKILL.md",
            f"registry/skill_packages/{owner or source_id}.json",
        ]
    elif kind == "script":
        base = [
            f".px/skills/{owner or 'audit-source-capabilities'}/scripts/{source_id.replace('-', '_')}.py"
        ]
    elif kind == "orchestration":
        base = [
            f"orchestration/workflows/reconstructed/{source_id}.yaml",
            f"registry/orchestration_outcomes/{source_id}.json",
        ]
    elif kind == "schema":
        base = [f"contracts/reconstructed/{source_id}.schema.json"]
    elif kind == "template":
        base = [f"bootstrap/templates/reconstructed/{source_id}.json"]
    elif kind == "reference-or-knowledge":
        base = [f"knowledge/operational/reconstructed/{source_id}.json"]
    else:
        base = [f"evidence/declared-suite/{kind}/{source_id}.json"]
    return base


def acceptance(kind: str, source_id: str) -> list[str]:
    common = [
        "Every declared source path is assigned exactly once and its consolidation rationale is recorded.",
        "The canonical owner and all consumers resolve through current registries without eager body hydration.",
        "Positive and malformed-input cases pass; denied or unsafe effects fail closed.",
    ]
    if kind == "orchestration":
        common.append(
            "Dependency order, budget, failure policy, rollback or compensation, and evidence outputs are executable and tested."
        )
    elif kind == "script":
        common.append(
            "The helper has deterministic structured output, a nonzero invalid-input exit, and direct unit tests."
        )
    elif kind == "skill":
        common.append(
            "The skill has a precise trigger, bounded workflow, safety boundary, verification method, package entry, and official validation receipt."
        )
    elif kind == "schema":
        common.append(
            "The schema is meta-valid and has valid, invalid, compatibility, owner, and consumer tests."
        )
    else:
        common.append(
            "The artifact is consumed by an executable surface and is not retained as disconnected prose or metadata."
        )
    return common


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--missing-csv", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--recovery-map", type=Path, required=True)
    parser.add_argument("--exact-recovery", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    with args.missing_csv.open(encoding="utf-8-sig", newline="") as handle:
        all_missing = list(csv.DictReader(handle))
    missing = [
        r
        for r in all_missing
        if r["pack"].startswith(ABSENT_PACK_PREFIXES) or r["pack"] == "registry"
    ]
    missing_by_path = {r["path"]: r for r in missing}
    if len(missing_by_path) != len(missing):
        raise SystemExit("duplicate paths in missing-artifact denominator")

    candidates = [
        c
        for c in load_json(args.candidates)["candidates"]
        if c["presence"] == "manifest-only"
        and not (c["kind"] == "script" and c["id"] == "init")
    ]
    recoveries = {
        (r["kind"], r["source_id"]): r for r in load_json(args.recovery_map)["records"]
    }
    exact_recoveries = {
        r["declared_path"]: r for r in load_json(args.exact_recovery)["records"]
    }
    if len(candidates) != 260 or len(recoveries) != 260:
        raise SystemExit(
            f"unexpected operational denominator: candidates={len(candidates)} recoveries={len(recoveries)}"
        )

    cards: list[dict] = []
    assigned: dict[str, str] = {}
    exact_recovered_outcomes: list[dict] = []

    for candidate in sorted(candidates, key=lambda item: (item["kind"], item["id"])):
        key = (candidate["kind"], candidate["id"])
        recovery = recoveries.get(key)
        if recovery is None:
            raise SystemExit(f"missing recovery owner for {key}")
        paths = sorted(
            p
            for p in (normalize_manifest_path(s["path"]) for s in candidate["sources"])
            if p in missing_by_path
        )
        if not paths:
            declared_paths = sorted(
                normalize_manifest_path(s["path"]) for s in candidate["sources"]
            )
            records = [exact_recoveries.get(path) for path in declared_paths]
            if not all(records) or not all(record["exact_match"] for record in records):
                raise SystemExit(
                    f"operational candidate has neither absent paths nor exact recoveries: {key}"
                )
            exact_recovered_outcomes.append(
                {
                    "kind": candidate["kind"],
                    "source_id": candidate["id"],
                    "canonical_owner": recovery["canonical_owner"],
                    "declared_paths": declared_paths,
                    "recovery_paths": [record["recovery_path"] for record in records],
                    "state": "exact_hash_recovered",
                }
            )
            continue
        card_id = f"REL-007-{candidate['kind'].upper()}-{slug(candidate['id']).upper()}"
        for path in paths:
            if path in assigned:
                raise SystemExit(f"multiply assigned path: {path}")
            assigned[path] = card_id
        pack = missing_by_path[paths[0]]["pack"]
        cards.append(
            {
                "card_id": card_id,
                "class": "operational_outcome",
                "pack": pack,
                "kind": candidate["kind"],
                "source_id": candidate["id"],
                "source_paths": paths,
                "canonical_owner": recovery["canonical_owner"],
                "current_state": "assigned_not_verified",
                "behavior_contract": inferred_behavior(
                    candidate["kind"], candidate["id"], pack
                ),
                "implementation_targets": targets(
                    candidate["kind"], candidate["id"], recovery["canonical_owner"]
                ),
                "wiring_targets": [
                    "registry/semantic_capability_index.json",
                    "registry/capability_aliases.json",
                    "registry/graphs",
                    "orchestration/workflows",
                ],
                "required_tests": [
                    f"tests/reconstruction/test_{candidate['kind']}_{candidate['id'].replace('-', '_')}.py"
                ],
                "acceptance": acceptance(candidate["kind"], candidate["id"]),
                "completion_evidence": [],
            }
        )

    support_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path, row in missing_by_path.items():
        if path not in assigned:
            support_groups[support_identity(row)].append(row)
    for (kind, source_id), rows in sorted(support_groups.items()):
        paths = sorted(row["path"] for row in rows)
        card_id = f"REL-007-SUPPORT-{slug(kind).upper()}-{source_id.upper()}"
        for path in paths:
            if path in assigned:
                raise SystemExit(f"multiply assigned support path: {path}")
            assigned[path] = card_id
        pack = rows[0]["pack"] if len({r["pack"] for r in rows}) == 1 else "cross-pack"
        behavior_pack = rows[0]["pack"]
        cards.append(
            {
                "card_id": card_id,
                "class": "supporting_artifact",
                "pack": pack,
                "kind": kind,
                "source_id": source_id,
                "source_paths": paths,
                "canonical_owner": "audit-source-capabilities",
                "current_state": "assigned_not_verified",
                "behavior_contract": inferred_behavior(kind, source_id, behavior_pack),
                "implementation_targets": targets(
                    kind, source_id, "audit-source-capabilities"
                ),
                "wiring_targets": [
                    "registry/contract_ownership.json",
                    "registry/artifact-provenance.json",
                    "tests/reconstruction",
                ],
                "required_tests": [
                    f"tests/reconstruction/test_support_{slug(kind).replace('-', '_')}_{source_id.replace('-', '_')}.py"
                ],
                "acceptance": acceptance(kind, source_id),
                "completion_evidence": [],
            }
        )

    unassigned = sorted(set(missing_by_path) - set(assigned))
    extras = sorted(set(assigned) - set(missing_by_path))
    if unassigned or extras or len(assigned) != 1133:
        raise SystemExit(
            f"coverage failure: assigned={len(assigned)} unassigned={len(unassigned)} extras={len(extras)}"
        )

    cards.sort(key=lambda c: c["card_id"])
    counts = Counter(card["class"] for card in cards)
    kind_counts = Counter(card["kind"] for card in cards)
    pack_counts = Counter(row["pack"] for row in missing)
    document = {
        "schema_version": "1.0",
        "status": "active_reconstruction",
        "completion_rule": "No card is complete until its implementation targets exist, its wiring resolves, and its required executable acceptance evidence passes.",
        "non_claim": "These cards reconstruct advertised outcomes, not unavailable historical bytes or undocumented historical behavior.",
        "summary": {
            "genuinely_absent_source_paths": len(missing),
            "assigned_source_paths": len(assigned),
            "unassigned_source_paths": 0,
            "operational_outcome_cards": counts["operational_outcome"],
            "exact_hash_recovered_operational_outcomes": len(exact_recovered_outcomes),
            "supporting_artifact_cards": counts["supporting_artifact"],
            "total_cards": len(cards),
            "verified_cards": 0,
            "open_cards": len(cards),
            "by_kind": dict(sorted(kind_counts.items())),
            "source_paths_by_pack": dict(sorted(pack_counts.items())),
        },
        "waves": [
            {"wave": 1, "packs": ["01"], "outcome": PACK_DOMAINS["01"]},
            {"wave": 2, "packs": ["02"], "outcome": PACK_DOMAINS["02"]},
            {"wave": 3, "packs": ["03"], "outcome": PACK_DOMAINS["03"]},
            {"wave": 4, "packs": ["04"], "outcome": PACK_DOMAINS["04"]},
            {"wave": 5, "packs": ["05"], "outcome": PACK_DOMAINS["05"]},
            {"wave": 6, "packs": ["06"], "outcome": PACK_DOMAINS["06"]},
            {"wave": 7, "packs": ["07", "registry"], "outcome": PACK_DOMAINS["07"]},
            {
                "wave": 8,
                "packs": ["all"],
                "outcome": "cross-pack integration, installed-package validation, sanitation, and revocable certification",
            },
        ],
        "exact_hash_recovered_outcomes": exact_recovered_outcomes,
        "cards": cards,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# Declared Suite Reconstruction Plan",
        "",
        "This is the executable REL-007 backlog. An owner route is assignment only; it is not completion evidence.",
        "",
        f"- Genuinely absent declared paths: {len(missing):,}",
        f"- Operational outcome cards: {counts['operational_outcome']:,}",
        f"- Operational outcomes already exact-hash recovered: {len(exact_recovered_outcomes):,}",
        f"- Supporting-artifact cards: {counts['supporting_artifact']:,}",
        f"- Total cards: {len(cards):,}",
        "- Initially verified cards: 0",
        "- Unassigned paths: 0",
        "",
        "## Execution order",
        "",
    ]
    for wave in document["waves"]:
        lines.append(
            f"{wave['wave']}. **{', '.join(wave['packs'])}** — {wave['outcome']}."
        )
    lines += [
        "",
        "## Completion gate",
        "",
        "A card closes only after its behavior contract is explicit, its canonical implementation exists, every wiring target resolves, required positive and negative tests pass, rollback or recovery is tested where effects exist, and evidence hashes are recorded in the ledger. Consolidation is allowed only when all declared consumers are covered by one stronger canonical implementation.",
        "",
        "## Card index",
        "",
        "| Card | Pack | Kind | Declared outcome/support | Owner | Paths | State |",
        "|---|---|---|---|---|---:|---|",
    ]
    for card in cards:
        lines.append(
            f"| `{card['card_id']}` | {card['pack']} | {card['kind']} | `{card['source_id']}` | `{card['canonical_owner']}` | {len(card['source_paths'])} | {card['current_state']} |"
        )
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(document["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
