"""One guarded controller for PACIFY-X pre-cert repository convergence.

Order:
  1. validate certification source/dependencies
  2. reconcile generated state to fixed point
  3. hash pre-commit admitted worktree
  4. fetch/classify Git relation
  5. stage/commit exact current source (optional execute mode)
  6. hash post-commit source
  7. push/fetch/verify exact upstream match (optional execute mode)
  8. re-hash and emit PRE_CERT_READY only when frozen and unchanged

This controller never starts the release-candidate runner or any certification
stage owner.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.pre_cert_contract import (  # noqa: E402
    CERTIFICATION_STEP_ORDER,
    EXECUTION_PATCH_FILES,
    READY_SEAL_SCHEMA,
    REQUIRED_CERT_ROOT_DEPENDENCIES,
    REQUIRED_REPO_ROOT_DEPENDENCIES,
)

# pre_cert_contract lives in px/py_cert/runtime, while the production runtime
# dependencies used by this controller live in the repository-root runtime
# package. Switch namespaces only after loading the certification contract.
REPO_ROOT = Path(__file__).resolve().parents[3]
_repo_root_text = str(REPO_ROOT)
if _repo_root_text in sys.path:
    sys.path.remove(_repo_root_text)
sys.path.insert(0, _repo_root_text)

# runtime was loaded above from px/py_cert. Remove that package binding so
# subsequent runtime.* imports resolve from REPO_ROOT.
sys.modules.pop("runtime", None)

from scripts.build_pre_cert_hash_manifest import build as build_hash_manifest  # noqa: E402
from scripts.converge_pre_cert_git import run as converge_git  # noqa: E402
from scripts.reconcile_pre_cert_generated_state import run as reconcile_generated  # noqa: E402


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def validate_source(root: Path) -> dict[str, Any]:
    cert_root = Path(__file__).resolve().parents[1]

    # The rebuilt execution patch is installed under px/py_cert, while its
    # production runtime/script dependencies remain canonical at repository
    # root. Do not require duplicate copies beneath the certification package.
    execution_patch = set(EXECUTION_PATCH_FILES)
    production_dependencies = tuple(
        p for p in REQUIRED_CERT_ROOT_DEPENDENCIES if p not in execution_patch
    )

    missing = (
        [f"cert:{p}" for p in EXECUTION_PATCH_FILES if not (cert_root / p).is_file()]
        + [f"repo:{p}" for p in production_dependencies if not (root / p).is_file()]
        + [f"repo:{p}" for p in REQUIRED_REPO_ROOT_DEPENDENCIES if not (root / p).is_file()]
    )

    syntax_errors: list[dict[str, str]] = []
    for rel in EXECUTION_PATCH_FILES:
        p = cert_root / rel
        if not p.is_file() or p.suffix != ".py":
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except Exception as exc:
            syntax_errors.append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})

    contract_error = None
    order = None
    try:
        from runtime.certification_contract import STEP_ORDER, validate_contract
        validate_contract()
        order = list(STEP_ORDER)
        if tuple(order) != CERTIFICATION_STEP_ORDER:
            contract_error = f"STEP_ORDER mismatch: {order!r}"
    except Exception as exc:
        contract_error = f"{type(exc).__name__}: {exc}"

    return {
        "valid": not missing and not syntax_errors and contract_error is None,
        "cert_root": str(cert_root),
        "missing_dependencies": missing,
        "syntax_errors": syntax_errors,
        "contract_error": contract_error,
        "step_order": order,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--output-root", type=Path, required=True,
                    help="Must be outside the repository; all reports/seals are written here.")
    ap.add_argument("--execute", action="store_true",
                    help="Permit generated reconciliation, staging/commit, and push.")
    ap.add_argument("--commit-message", default="Pre-cert repository convergence")
    ap.add_argument("--no-push", action="store_true")
    ns = ap.parse_args()

    root = ns.root.resolve()
    output = ns.output_root.resolve()
    try:
        output.relative_to(root)
        raise SystemExit("--output-root must be outside the repository")
    except ValueError:
        pass
    output.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {"created_utc": now(), "root": str(root), "output_root": str(output), "execute": ns.execute, "steps": {}}

    source = validate_source(root)
    report["steps"]["01_certification_source"] = source
    write_json(output / "01-certification-source-validation.json", source)
    if not source["valid"]:
        report["valid"] = False
        report["blocked_at"] = "01_certification_source"
        write_json(output / "pre-cert-convergence-summary.json", report)
        return 2

    if ns.execute:
        generated = reconcile_generated(root)
    else:
        # Audit-only mode validates current state without invoking the mutating rebuild.
        try:
            from runtime.generated_artifacts import validate_generated_artifacts
            from runtime.release_artifacts import classify_tree
            gv = validate_generated_artifacts(root)
            ct = classify_tree(root)
            generated = {"schema_version": "audit-only", "valid": gv.get("valid") is True and ct.get("valid") is True and ct.get("product_valid") is True,
                         "errors": [], "validation": gv, "classification": ct, "fixed_point": None}
            if not generated["valid"]:
                generated["errors"] = ["GENERATED_STATE_NOT_CURRENT"]
        except Exception as exc:
            generated = {"schema_version": "audit-only", "valid": False, "errors": ["GENERATED_AUDIT_FAILED"], "error": f"{type(exc).__name__}: {exc}"}
    report["steps"]["02_generated_state"] = generated
    write_json(output / "02-generated-state.json", generated)
    if not generated.get("valid"):
        report["valid"] = False
        report["blocked_at"] = "02_generated_state"
        write_json(output / "pre-cert-convergence-summary.json", report)
        return 2

    pre = build_hash_manifest(root)
    report["steps"]["03_precommit_manifest"] = {k: pre.get(k) for k in ("valid_structure", "counts", "tracked_content_sha256", "admitted_worktree_content_sha256", "git")}
    write_json(output / "03-precommit-hash-manifest.json", pre)
    if not pre.get("valid_structure"):
        report["valid"] = False; report["blocked_at"] = "03_precommit_manifest"
        write_json(output / "pre-cert-convergence-summary.json", report); return 2

    git_result = converge_git(root, fetch=True, stage_all=ns.execute,
                              commit_message=ns.commit_message if ns.execute else None,
                              push=(ns.execute and not ns.no_push),
                              require_final_match=ns.execute)
    report["steps"]["04_git_convergence"] = git_result
    write_json(output / "04-git-convergence.json", git_result)
    if not git_result.get("valid"):
        report["valid"] = False; report["blocked_at"] = "04_git_convergence"
        write_json(output / "pre-cert-convergence-summary.json", report); return 2

    if not ns.execute:
        report["valid"] = True
        report["blocked_at"] = None
        report["status"] = "AUDIT_READY_TO_CONVERGE"
        write_json(output / "pre-cert-convergence-summary.json", report)
        print(json.dumps({"status": report["status"], "precommit": report["steps"]["03_precommit_manifest"], "git": git_result}, indent=2, ensure_ascii=False))
        return 0

    post = build_hash_manifest(root)
    write_json(output / "05-postconvergence-hash-manifest.json", post)
    report["steps"]["05_postconvergence_manifest"] = {k: post.get(k) for k in ("valid_structure", "counts", "tracked_content_sha256", "admitted_worktree_content_sha256", "git")}

    final_git = post["git"]
    status_lines = final_git.get("status_porcelain_v2", [])
    head_match = bool(final_git.get("upstream_head")) and final_git.get("head") == final_git.get("upstream_head")
    clean = not [line for line in status_lines if line and not line.startswith("#")]
    no_untracked = post["counts"]["untracked_nonignored"] == 0

    seal = {
        "schema_version": READY_SEAL_SCHEMA,
        "created_utc": now(),
        "status": "PRE_CERT_READY" if (post.get("valid_structure") and head_match and clean and no_untracked) else "BLOCKED",
        "root": str(root),
        "branch": final_git.get("branch"),
        "head": final_git.get("head"),
        "tree": final_git.get("tree"),
        "upstream": final_git.get("upstream"),
        "upstream_head": final_git.get("upstream_head"),
        "tracked_content_sha256": post.get("tracked_content_sha256"),
        "admitted_worktree_content_sha256": post.get("admitted_worktree_content_sha256"),
        "hash_manifest_sha256": sha256_json(post),
        "certification_step_order": list(CERTIFICATION_STEP_ORDER),
        "conditions": {
            "structure_valid": bool(post.get("valid_structure")),
            "head_matches_upstream": head_match,
            "working_tree_clean": clean,
            "no_nonignored_untracked_files": no_untracked,
            "generated_state_green": bool(generated.get("valid")),
            "certification_source_green": bool(source.get("valid")),
        },
    }
    seal["seal_sha256"] = sha256_json(seal)
    write_json(output / "06-PRE_CERT_READY.json", seal)
    report["steps"]["06_ready_seal"] = seal
    report["valid"] = seal["status"] == "PRE_CERT_READY"
    report["blocked_at"] = None if report["valid"] else "06_ready_seal"
    write_json(output / "pre-cert-convergence-summary.json", report)
    print(json.dumps(seal, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
