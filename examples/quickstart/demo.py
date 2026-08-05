#!/usr/bin/env python3
"""Run a small, source-checkout PACIFY-X lifecycle and retain its evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def _run(*arguments: str) -> dict:
    command = [sys.executable, "-m", "runtime.cli", "--root", str(ROOT), *arguments]
    result = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, timeout=60
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}"
        )
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded PACIFY-X quickstart demonstration."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New directory that will retain the demo project and evidence",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("--output must name a path that does not exist")
    evidence = output / "evidence"
    project = output / "project"
    evidence.mkdir(parents=True)

    steps: dict[str, object] = {}
    steps["framework_validation"] = _run("validate")
    steps["initialization_preview"] = _run(
        "commission", "--mode", "new", "--project", str(project)
    )
    steps["initialization"] = _run(
        "commission", "--mode", "new", "--project", str(project), "--apply"
    )
    task = "validate a bounded project with retained evidence"
    steps["classification"] = _run("classify", "--task", task)
    selection = _run("working-set", "--goal", task)
    steps["selection"] = selection
    selected = str(selection["capability_ids"][0])
    hydration = _run("hydrate", "--skill", selected)
    steps["hydration"] = {
        "valid": hydration["valid"],
        "selected": selected,
        "active_ids": hydration["active_ids"],
        "bytes_loaded": hydration["bytes_loaded"],
        "release": hydration["release"],
    }
    steps["bounded_dry_run"] = _run(
        "commission", "--mode", "new", "--project", str(output / "dry-run-project")
    )
    steps["verification"] = _run("project-check", "--project", str(project))

    valid = all(
        bool(value.get("valid", True))
        for value in steps.values()
        if isinstance(value, dict)
    )
    receipt = {
        "schema_version": "1.0",
        "valid": valid,
        "project": "project",
        "changed_paths": ["project/", "evidence/demo-receipt.json"],
        "effects": [
            "create explicitly requested demo output",
            "no network",
            "no deletion",
        ],
        "steps": steps,
    }
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["receipt_sha256"] = hashlib.sha256(canonical).hexdigest()
    path = evidence / "demo-receipt.json"
    path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "valid": valid,
                "evidence": str(path),
                "receipt_sha256": receipt["receipt_sha256"],
            },
            indent=2,
        )
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
