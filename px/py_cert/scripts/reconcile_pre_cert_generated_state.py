"""Reconcile generated repository state to a proven fixed point before Git freeze.

This is intentionally a pre-cert source preparation operation.  It must run
before the final hash manifest/commit and must never advance release campaign
state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.pre_cert_contract import GENERATED_RECONCILE_SCHEMA  # noqa: E402

# pre_cert_contract lives in px/py_cert/runtime, but the generated-state
# implementation imported by run() lives in the repository-root runtime
# package. Switch namespaces only after loading the certification contract.
REPO_ROOT = Path(__file__).resolve().parents[3]
_repo_root_text = str(REPO_ROOT)
if _repo_root_text in sys.path:
    sys.path.remove(_repo_root_text)
sys.path.insert(0, _repo_root_text)

# runtime was loaded above from px/py_cert. Remove that package binding so
# later imports such as runtime.generated_artifacts resolve from REPO_ROOT.
sys.modules.pop("runtime", None)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git_paths(root: Path) -> list[str]:
    cp = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True, check=True, timeout=120,
    )
    return [p.decode("utf-8", "surrogateescape") for p in cp.stdout.split(b"\0") if p]


def snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for rel in sorted(git_paths(root), key=str.casefold):
        p = root / rel
        if not os.path.lexists(p):
            continue
        if p.is_symlink():
            result[rel.replace("\\", "/")] = "L:" + hashlib.sha256(os.readlink(p).encode()).hexdigest()
        elif p.is_file():
            h = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            result[rel.replace("\\", "/")] = "F:" + h.hexdigest()
    return result


def delta(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    keys = set(before) | set(after)
    return {
        "added": sorted([k for k in keys if k not in before], key=str.casefold),
        "removed": sorted([k for k in keys if k not in after], key=str.casefold),
        "changed": sorted([k for k in keys if k in before and k in after and before[k] != after[k]], key=str.casefold),
    }


def valid_generated(result: Any) -> bool:
    return isinstance(result, dict) and result.get("valid") is True


def run(root: Path) -> dict[str, Any]:
    root = root.resolve()
    try:
        from runtime.generated_artifacts import validate_generated_artifacts
        from runtime.release_artifacts import classify_tree
        from scripts.clean_source_export import _rebuild_candidate_projections
    except Exception as exc:
        return {
            "schema_version": GENERATED_RECONCILE_SCHEMA, "created_utc": now(), "valid": False,
            "errors": ["RECONCILE_IMPORT_FAILED"], "error": f"{type(exc).__name__}: {exc}",
        }

    before = snapshot(root)
    validation_before = validate_generated_artifacts(root)

    _rebuild_candidate_projections(root)
    after_first = snapshot(root)
    validation_first = validate_generated_artifacts(root)
    classification_first = classify_tree(root)

    _rebuild_candidate_projections(root)
    after_second = snapshot(root)
    validation_second = validate_generated_artifacts(root)
    classification_second = classify_tree(root)

    first_delta = delta(before, after_first)
    second_delta = delta(after_first, after_second)
    fixed = not any(second_delta.values())
    generated_ok = valid_generated(validation_second)
    classification_ok = isinstance(classification_second, dict) and classification_second.get("valid") is True and classification_second.get("product_valid") is True
    errors: list[str] = []
    if not generated_ok:
        errors.append("GENERATED_ARTIFACT_VALIDATION_FAILED")
    if not classification_ok:
        errors.append("TREE_CLASSIFICATION_FAILED")
    if not fixed:
        errors.append("GENERATED_FIXED_POINT_FAILED")

    return {
        "schema_version": GENERATED_RECONCILE_SCHEMA,
        "created_utc": now(),
        "valid": not errors,
        "errors": errors,
        "validation_before": validation_before,
        "validation_after_first": validation_first,
        "validation_after_second": validation_second,
        "classification_after_first": classification_first,
        "classification_after_second": classification_second,
        "first_pass_delta": first_delta,
        "second_pass_delta": second_delta,
        "fixed_point": fixed,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--output", type=Path, required=True)
    ns = ap.parse_args()
    result = run(ns.root)
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"schema_version": result.get("schema_version"), "valid": result.get("valid"), "errors": result.get("errors", []), "fixed_point": result.get("fixed_point")}, indent=2))
    return 0 if result.get("valid") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
