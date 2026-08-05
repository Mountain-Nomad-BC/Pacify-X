"""Assign every inventory record a required class or explicit review state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_common import read_jsonl, write_jsonl  # noqa: E402

CLASSES = {
    "skill",
    "orchestration",
    "builder",
    "contract",
    "policy",
    "repair_pattern",
    "template",
    "test_pattern",
    "evidence_pattern",
    "research_extraction",
    "knowledge_reference_only",
    "duplicate",
    "unsafe_untrusted",
    "clean_room_required",
    "not_applicable",
}


def classify(item: dict, duplicate_ids: set[str]) -> tuple[str, float, str]:
    if item["id"] in duplicate_ids:
        return "duplicate", 1.0, "canonical_selection_required"
    path = item["path"].casefold()
    headings = " ".join(item.get("structure", {}).get("headings", [])).casefold()
    value = f"{path} {headings}"
    suffix = item.get("extension", "")
    if suffix in {".exe", ".dll", ".so", ".dylib", ".bin"}:
        return "unsafe_untrusted", 0.98, "quarantine"
    rules = (
        ("skill", ("skill.md", "/skills/", "skill_"), "admission_required"),
        ("orchestration", ("orchestrat", "workflow", "dag"), "review"),
        ("builder", ("builder", "compiler", "generator"), "review"),
        ("contract", ("contract", "schema", "manifest"), "review"),
        ("policy", ("policy", "governance", "approval"), "review"),
        ("repair_pattern", ("repair", "remediation", "fix"), "review"),
        ("template", ("template", "scaffold", "boilerplate"), "review"),
        ("test_pattern", ("/tests/", "test_", "validation"), "reference_only"),
        ("evidence_pattern", ("evidence", "attestation", "proof"), "reference_only"),
        (
            "research_extraction",
            ("paper", "research", "arxiv", "benchmark"),
            "reference_only",
        ),
    )
    for name, tokens, state in rules:
        score = sum(token in value for token in tokens)
        if score:
            return name, min(0.99, 0.7 + 0.08 * score), state
    if item.get("content_kind") == "binary":
        return "not_applicable", 0.9, "excluded_binary"
    if not item.get("structure", {}).get("headings") and suffix not in {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".go",
        ".java",
        ".cs",
    }:
        return "knowledge_reference_only", 0.65, "reference_only"
    return "clean_room_required", 0.55, "triage"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--exact-duplicates", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    duplicate_ids: set[str] = set()
    if args.exact_duplicates and args.exact_duplicates.is_file():
        data = json.loads(args.exact_duplicates.read_text(encoding="utf-8"))
        for group in data.get("groups", []):
            duplicate_ids.update(group["members"][1:])
    records = []
    for item in read_jsonl(args.inventory):
        asset_class, confidence, review_state = classify(item, duplicate_ids)
        assert asset_class in CLASSES
        records.append(
            {
                "id": item["id"],
                "source_tree": item["source_tree"],
                "path": item["path"],
                "class": asset_class,
                "confidence": confidence,
                "review_state": review_state,
                "probable_domain": item["probable_domain"],
                "sha256": item["sha256"],
            }
        )
    records.sort(
        key=lambda item: (
            item["class"],
            item["probable_domain"],
            item["source_tree"],
            item["path"],
        )
    )
    count, digest = write_jsonl(args.output, records)
    summary = {
        "schema_version": "1.0",
        "record_count": count,
        "unknown_count": 0,
        "classes_present": sorted({item["class"] for item in records}),
        "output_sha256": digest,
    }
    args.output.with_name("asset_classification_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
