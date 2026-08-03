#!/usr/bin/env python3
"""Build a readable recovery ledger from a manifest/filesystem reconciliation."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def classify(path: str) -> tuple[str, str]:
    checks = (
        ("/skills/", "skill-component", "Recover an authoritative behavior contract or specification; clean-room implement or merge into a canonical skill; add discriminating tests; validate and map."),
        ("/orchestrations/", "orchestration", "Recover the workflow contract; rebuild a bounded DAG with dependencies, effects, failure policy, rollback, and acceptance tests."),
        ("/scripts/", "script", "Recover behavior and I/O contracts; clean-room implement without executing intake code; add positive, negative, and hostile-input tests."),
        ("/schemas/", "schema", "Recover field semantics and consumers; implement the canonical schema; validate examples, negative cases, and compatibility."),
        ("/tests/", "test-or-evaluation", "Recover acceptance intent independently; rebuild discriminating cases and execute them against the canonical owner."),
        ("/evaluations/", "test-or-evaluation", "Recover acceptance intent independently; rebuild discriminating cases and execute them against the canonical owner."),
        ("/evidence/", "evidence", "Do not recreate historical proof from filenames; regenerate evidence only from successful current validations."),
        ("/registry/", "registry", "Regenerate from admitted canonical owners after all dependent bodies and contracts exist."),
        ("/references/", "reference-or-knowledge", "Recover authoritative source material or reconstruct a sanitized, cited reference; bind it to a specific skill trigger."),
        ("/knowledge/", "reference-or-knowledge", "Recover authoritative source material or reconstruct a sanitized, cited reference; bind it to a specific skill trigger."),
        ("/templates/", "template", "Recover required fields and consuming contract; rebuild the minimal schema-bound template and validate round trips."),
    )
    normalized = f"/{path.strip('/')}"
    for marker, kind, action in checks:
        if marker in normalized:
            return kind, action
    return "pack-metadata", "Recover or reconstruct only if required by an admitted owner; otherwise record a justified non-admission."


def build(manifest_path: Path, reconciliation_path: Path) -> tuple[list[dict], dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reconciliation = json.loads(reconciliation_path.read_text(encoding="utf-8"))
    missing = set(reconciliation["missing_paths"])
    rows = []
    for item in manifest["files"]:
        path = item["path"]
        if path not in missing:
            continue
        parts = path.split("/")
        pack = parts[1] if parts[0] == "packs" and len(parts) > 1 else parts[0]
        kind, action = classify(path)
        rows.append({
            "pack": pack,
            "artifact_type": kind,
            "path": path,
            "expected_bytes": item["bytes"],
            "expected_sha256": item["sha256"],
            "intake_state": "missing",
            "evidence_state": "manifest-only",
            "rebuild_ready": False,
            "required_action": action,
        })
    rows.sort(key=lambda row: (row["pack"], row["path"]))
    return rows, reconciliation


def write_outputs(rows: list[dict], reconciliation: dict, markdown_path: Path, csv_path: Path) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Missing Declared Artifacts and Recovery Backlog",
        "",
        "This ledger compares the suite manifest with physical files in the final intake. It records manifest claims that have no file body in the intake. It does **not** identify empty directories in the bootstrap product.",
        "",
        f"- Manifest-declared files: {reconciliation['manifest_declared_file_count']}",
        f"- Physically present and hash-matching: {reconciliation['present_and_matching']}",
        f"- Missing declared files: {reconciliation['missing_declared_files']}",
        f"- Present hash/size mismatches: {reconciliation['hash_or_size_mismatches']}",
        f"- Unexpected physical files: {reconciliation['unexpected_files']}",
        "",
        "A filename, expected size, and hash prove that an artifact was intended; they do not reveal its missing contents. No missing item may be called implemented merely by recreating its name. Each needs an authoritative source or a clean-room behavior contract, implementation/merge decision, discriminating validation, mapping, and current evidence.",
        "",
        "## Missing by pack",
        "",
        "| Pack | Missing |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in reconciliation["missing_by_pack"].items())
    lines.extend(["", "## Missing by artifact type", "", "| Artifact type | Missing |", "|---|---:|"])
    lines.extend(f"| {name} | {count} |" for name, count in sorted(Counter(row["artifact_type"] for row in rows).items()))
    lines.extend(["", "## Full recovery backlog", ""])
    lines.extend(f"- [ ] `{row['path']}` — {row['artifact_type']}; expected {row['expected_bytes']} bytes; SHA-256 `{row['expected_sha256']}`" for row in rows)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    rows, reconciliation = build(args.manifest, args.reconciliation)
    write_outputs(rows, reconciliation, args.markdown, args.csv)
    print(json.dumps({"missing_records": len(rows), "markdown": str(args.markdown), "csv": str(args.csv)}, sort_keys=True))
    return 0 if len(rows) == reconciliation["missing_declared_files"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
