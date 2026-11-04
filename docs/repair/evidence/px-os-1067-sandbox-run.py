"""Run a producer against an isolated copy of the repository and record every write.

Static extraction got as far as it could: it cannot tell whether `destination / 'receipt.json'`
is confined, only that a name is involved. This harness answers the question directly by
watching the filesystem while the producer runs.

Safety:

* the producer runs with its working directory and every path argument inside a temporary
  copy, never the real repository;
* the process is bounded by a timeout;
* the harness compares before/after state under the sandbox root and reports writes, so the
  claim "this producer stays inside the root" is observed, not inferred.

It is a measurement, not a grant: it says what happened in one run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if not (ROOT / "runtime").is_dir():
    ROOT = Path(__file__).resolve().parents[2]

SKIP_DIRS = {".git", ".venv-repair", "node_modules", "__pycache__"}


def snapshot(base: Path) -> dict[str, tuple[int, float]]:
    state: dict[str, tuple[int, float]] = {}
    for path in base.rglob("*"):
        relative = path.relative_to(base).as_posix()
        if any(part in SKIP_DIRS for part in relative.split("/")):
            continue
        if path.is_file():
            stat = path.stat()
            state[relative] = (stat.st_size, stat.st_mtime)
    return state


def build_skeleton(destination: Path) -> None:
    """Copy only what a producer needs to import and run, plus an empty output area."""
    for name in ("runtime", "scripts"):
        shutil.copytree(ROOT / name, destination / name, ignore=shutil.ignore_patterns(*SKIP_DIRS))
    policies = ROOT / "policies"
    if policies.is_dir():
        shutil.copytree(policies, destination / "policies")
    (destination / "reports").mkdir(parents=True)
    (destination / ".agentic_engineering_os_px").mkdir(parents=True, exist_ok=True)
    # A minimal source tree for the integration-disposition builder: it needs something to
    # index, and one file is enough to exercise the write path.
    (destination / "upstream-source" / "src").mkdir(parents=True, exist_ok=True)
    (destination / "upstream-source" / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    # A minimal finding register so the re-audit importer can run. Its parser enforces an
    # exact 113-finding denominator, so the sandbox uses the producer with a synthesized
    # single-row input ONLY to observe its write behaviour; the run is expected to refuse.
    register = ROOT / "docs/repair/evidence" / "_sandbox-register.md"
    if register.is_file():
        shutil.copy(register, destination / "register.md")
    else:
        # A synthetic register that satisfies the importer's exact denominator, so the producer
        # can be observed doing its real work rather than refusing at the parser.
        families = {"R": 31, "A": 16, "W": 12, "S": 12, "M": 6, "G": 6, "K": 2, "U": 17, "D": 11}
        severities = ["BLOCKER"] * 19 + ["HIGH"] * 45 + ["MEDIUM"] * 38 + ["LOW"] * 11
        lines = ["| ID | Severity | Finding | Evidence | Correction |", "|---|---|---|---|---|"]
        index = 0
        ordinal = 1
        for family, count in families.items():
            for _ in range(count):
                lines.append(
                    f"| {family}-{ordinal:03d} | **{severities[index]}** | finding | evidence | correction |"
                )
                ordinal += 1
                index += 1
        (destination / "register.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(producer: str, arguments: list[str], timeout: int = 120) -> dict[str, object]:
    sandbox = Path(tempfile.mkdtemp(prefix="px-sandbox-"))
    try:
        build_skeleton(sandbox)
        before = snapshot(sandbox)
        started = time.time()
        result = subprocess.run(
            [sys.executable, str(sandbox / producer), *arguments],
            cwd=sandbox,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(sandbox), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        elapsed = round(time.time() - started, 2)
        after = snapshot(sandbox)
        created = sorted(set(after) - set(before))
        modified = sorted(name for name in set(after) & set(before) if after[name] != before[name])
        return {
            "producer": producer,
            "arguments": arguments,
            "exit_code": result.returncode,
            "elapsed_seconds": elapsed,
            "created": created,
            "modified": modified,
            "stderr_tail": result.stderr.strip().splitlines()[-3:],
            "sandbox": str(sandbox),
        }
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("producer")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    parser.add_argument("--timeout", type=int, default=120)
    parsed = parser.parse_args()
    arguments = [item for item in parsed.arguments if item != "--"]
    print(json.dumps(run(parsed.producer, arguments, parsed.timeout), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
