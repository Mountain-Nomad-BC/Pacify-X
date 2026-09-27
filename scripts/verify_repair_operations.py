"""Produce artifact-bound, source-operational proof before repair freeze.

This is deliberately narrower than the owned full profile, validation, install,
or certification. It runs only in-process checks while the campaign is closed,
zero-denominator, and in operational verification.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
import tomllib
import uuid
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.test_profiles import (
    PROJECT_REPAIR_CAMPAIGN_PATH,
    ProcessingOrderBlocked,
    repair_campaign_status,
    require_processing_stage,
)
from runtime.version import VERSION


def _write_new_json(path: Path, value: dict[str, Any]) -> str:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cli_observation(argv: list[str]) -> dict[str, Any]:
    from runtime.cli import main

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        try:
            exit_code = main(argv)
        except SystemExit as error:
            exit_code = error.code
    if exit_code not in (0, None):
        raise ProcessingOrderBlocked(f"CLI smoke exited {exit_code}")
    return {"argv": argv, "stdout": output.getvalue().strip(), "exit_code": 0}


def _version_observation(root: Path) -> dict[str, Any]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extension = json.loads((root / "extension/package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "extension/package-lock.json").read_text(encoding="utf-8"))
    versions = {
        "pyproject": pyproject["project"]["version"],
        "runtime": VERSION,
        "extension": extension["version"],
        "extension_lock": lock["version"],
        "extension_lock_root": lock["packages"][""]["version"],
    }
    if len(set(versions.values())) != 1:
        raise ProcessingOrderBlocked(f"source version identities disagree: {versions}")
    parts = [int(part) for part in VERSION.split(".")]
    if len(parts) != 3 or tuple(parts) < (0, 9, 0):
        raise ProcessingOrderBlocked("source version must be at least 0.9.0")
    return {"versions": versions}


def produce_operational_verification(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    status = repair_campaign_status(root)
    if (
        not status["managed"] or not status["valid"]
        or status["phase"] != "operational_verification"
        or status["intake_open"] or status["unresolved"]
    ):
        raise ProcessingOrderBlocked("operational proof requires closed zero-denominator intake")
    require_processing_stage(root, "operational_verification")
    campaign_path = root / PROJECT_REPAIR_CAMPAIGN_PATH
    campaign_bytes = campaign_path.read_bytes()
    campaign = json.loads(campaign_bytes)
    relative_base = Path(".engineering-bootstrap/processing-order/operational-verification")
    current = root
    for part in relative_base.parts:
        current = current / part
        if current.is_symlink():
            raise ProcessingOrderBlocked("operational evidence path contains a symbolic link")
    evidence_root = root / relative_base
    evidence_root.mkdir(parents=True, exist_ok=True)
    run_dir = evidence_root / uuid.uuid4().hex
    run_dir.mkdir()

    checks: list[dict[str, Any]] = []
    operations: tuple[tuple[str, Callable[[], dict[str, Any]]], ...] = (
        ("campaign-state", lambda: {"status": repair_campaign_status(root)}),
        ("processing-order-cli", lambda: _cli_observation([
            "--root", str(root), "processing-order", "check", "--project", str(root),
            "--stage", "operational_verification",
        ])),
        ("version-alignment", lambda: _version_observation(root)),
        ("runtime-cli-version", lambda: _cli_observation(["--version"])),
    )
    for name, operation in operations:
        try:
            observed = operation()
            passed = name != "campaign-state" or (
                observed["status"]["valid"] and observed["status"]["unresolved_count"] == 0
            )
            if name == "processing-order-cli":
                parsed = json.loads(observed["stdout"])
                passed = passed and parsed.get("valid") is True
            if name == "runtime-cli-version":
                passed = passed and observed["stdout"] == f"engineering-bootstrap {VERSION}"
            artifact = {"name": name, "passed": bool(passed), "observed": observed}
        except Exception as error:
            passed = False
            artifact = {"name": name, "passed": False, "error_type": type(error).__name__, "error": str(error)[:1000]}
        artifact_path = run_dir / f"{name}.json"
        digest = _write_new_json(artifact_path, artifact)
        checks.append({
            "name": name, "passed": bool(passed), "exit_code": 0 if passed else 1,
            "artifact": artifact_path.relative_to(root).as_posix(), "artifact_sha256": digest,
        })
    receipt = {
        "schema_version": "px.operational-verification/1.0",
        "valid": all(check["passed"] for check in checks),
        "campaign_id": campaign["campaign_id"],
        "campaign_state_sha256": hashlib.sha256(campaign_bytes).hexdigest(),
        "unresolved_count": 0,
        "checks": checks,
        "scope": "pre-freeze source-operational smoke; not full profile or installed certification",
    }
    receipt_path = run_dir / "receipt.json"
    _write_new_json(receipt_path, receipt)
    return {"receipt": receipt_path.relative_to(root).as_posix(), **receipt}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    result = produce_operational_verification(args.project)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
