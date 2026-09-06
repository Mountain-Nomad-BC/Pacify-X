"""Build exact successor release configs from a terminal predecessor pair."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def replace_tree(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, dict):
        return {key: replace_tree(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_tree(item, replacements) for item in value]
    if isinstance(value, str):
        for before, after in replacements:
            value = value.replace(before, after)
    return value


def write_new(path: Path, value: object) -> None:
    if path.exists():
        raise ValueError(f"successor output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--automation-base", type=Path, required=True)
    parser.add_argument("--stage-base", type=Path, required=True)
    parser.add_argument("--automation-output", type=Path, required=True)
    parser.add_argument("--stage-output", type=Path, required=True)
    parser.add_argument("--old-prefix", required=True)
    parser.add_argument("--new-prefix", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--predecessor-id", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--artifact-size", type=int, required=True)
    parser.add_argument("--artifact-mtime-ns", type=int, required=True)
    parser.add_argument("--artifact-entry-count", type=int, required=True)
    parser.add_argument("--installed-directory", required=True)
    parser.add_argument("--installed-tree-digest", required=True)
    parser.add_argument("--installed-version", required=True)
    parser.add_argument("--installed-entry-count", type=int, required=True)
    parser.add_argument("--prior-tag-target", required=True)
    args = parser.parse_args()

    automation_base = json.loads(args.automation_base.read_text(encoding="utf-8"))
    stage_base = json.loads(args.stage_base.read_text(encoding="utf-8"))
    replacements = [
        (str(automation_base["candidate_id"]), args.candidate_id),
        (args.old_prefix, args.new_prefix),
        (str(automation_base["artifact_sha256"]), args.artifact_sha256),
        (str(automation_base["artifact"]), args.artifact),
        (str(automation_base["artifact_size"]), str(args.artifact_size)),
        (str(automation_base["artifact_mtime_ns"]), str(args.artifact_mtime_ns)),
        (str(stage_base["install"]["tree_digest"]), args.installed_tree_digest),
        ("0.6.85", args.installed_version),
    ]
    automation = replace_tree(automation_base, replacements)
    stage = replace_tree(stage_base, replacements)
    automation.update(
        candidate_id=args.candidate_id,
        predecessor_campaign_id=args.predecessor_id,
        evidence_prefix=args.new_prefix,
        artifact=args.artifact,
        artifact_sha256=args.artifact_sha256,
        artifact_size=args.artifact_size,
        artifact_mtime_ns=args.artifact_mtime_ns,
    )
    stage.update(candidate_id=args.candidate_id, predecessor_id=args.predecessor_id)
    stage["artifact"].update(
        path=args.artifact,
        sha256=args.artifact_sha256,
        size=args.artifact_size,
        mtime_ns=args.artifact_mtime_ns,
        entry_count=args.artifact_entry_count,
    )
    stage["identity"].update(
        path_manifest=f".engineering-bootstrap/processing-order/{args.new_prefix}-source-manifest.json",
        commit_message=f"Freeze {args.new_prefix} reconciled release state",
        prior_tag_target=args.prior_tag_target,
    )
    stage["install"].update(
        directory=args.installed_directory,
        tree_digest=args.installed_tree_digest,
        version=args.installed_version,
        entry_count=args.installed_entry_count,
    )
    write_new(args.automation_output, automation)
    write_new(args.stage_output, stage)
    print(json.dumps({"automation": str(args.automation_output), "stage": str(args.stage_output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
