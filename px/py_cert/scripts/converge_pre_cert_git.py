"""Guarded Git convergence for the already-repaired pre-cert source tree.

No merge, rebase, force-push, tag movement, or certification-stage execution is
performed.  Divergence blocks and must be resolved deliberately.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.pre_cert_contract import GIT_CONVERGENCE_SCHEMA, GIT_TRANSIENT_SENTINELS  # noqa: E402

HEX40 = re.compile(r"^[0-9a-f]{40}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git(root: Path, *args: str, timeout: int = 180) -> str:
    cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", check=False, timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(cp.stderr or cp.stdout).strip()}")
    return cp.stdout


def repo_state(root: Path) -> dict[str, Any]:
    git_dir = Path(str(git(root, "rev-parse", "--git-dir")).strip())
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    operations = [name for name in GIT_TRANSIENT_SENTINELS if (git_dir / name).exists()]
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        operations.append("REBASE")
    branch = git(root, "branch", "--show-current").strip()
    head = git(root, "rev-parse", "HEAD").strip()
    tree = git(root, "rev-parse", "HEAD^{tree}").strip()
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    try:
        upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip()
        upstream_head = git(root, "rev-parse", "@{u}").strip()
    except Exception:
        upstream = None
        upstream_head = None
    return {"branch": branch, "head": head, "tree": tree, "status": status,
            "upstream": upstream, "upstream_head": upstream_head, "operations": operations}


def is_ancestor(root: Path, older: str, newer: str) -> bool:
    cp = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
                        capture_output=True, check=False, timeout=60)
    return cp.returncode == 0


def run(root: Path, *, fetch: bool, stage_all: bool, commit_message: str | None, push: bool, require_final_match: bool = True) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    actions: list[str] = []

    initial = repo_state(root)
    if initial["operations"]:
        errors.append("GIT_OPERATION_IN_PROGRESS")
    if not initial["branch"]:
        errors.append("DETACHED_HEAD")
    if not initial["upstream"]:
        errors.append("UPSTREAM_NOT_CONFIGURED")
    if errors:
        return {"schema_version": GIT_CONVERGENCE_SCHEMA, "created_utc": now(), "valid": False,
                "errors": errors, "actions": actions, "initial": initial}

    if fetch:
        git(root, "fetch", "--prune")
        actions.append("fetch --prune")
    fetched = repo_state(root)

    if fetched["upstream_head"] and fetched["head"] != fetched["upstream_head"]:
        local_ahead = is_ancestor(root, fetched["upstream_head"], fetched["head"])
        remote_ahead = is_ancestor(root, fetched["head"], fetched["upstream_head"])
        if remote_ahead and not local_ahead:
            errors.append("REMOTE_AHEAD_BLOCKS_CONVERGENCE")
        elif not local_ahead and not remote_ahead:
            errors.append("LOCAL_REMOTE_DIVERGED")

    if errors:
        return {"schema_version": GIT_CONVERGENCE_SCHEMA, "created_utc": now(), "valid": False,
                "errors": errors, "actions": actions, "initial": initial, "after_fetch": fetched}

    if stage_all:
        git(root, "add", "-A", "--", ".")
        actions.append("add -A -- .")

    staged_names = [x for x in git(root, "diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB").splitlines() if x]
    if commit_message:
        if not staged_names:
            actions.append("commit skipped: no staged changes")
        else:
            git(root, "commit", "-m", commit_message, timeout=300)
            actions.append("commit")

    committed = repo_state(root)
    if require_final_match and committed["status"]:
        errors.append("WORKTREE_NOT_CLEAN_AFTER_COMMIT")

    if push and not errors:
        # Never force. Explicit branch target prevents accidental detached/ref push.
        upstream = committed["upstream"]
        assert upstream
        remote, remote_branch = upstream.split("/", 1)
        git(root, "push", remote, f"HEAD:{remote_branch}", timeout=300)
        actions.append(f"push {remote} HEAD:{remote_branch}")
        git(root, "fetch", remote, "--prune", timeout=180)
        actions.append(f"fetch {remote} --prune")

    final = repo_state(root)
    if require_final_match and final["upstream_head"] != final["head"]:
        errors.append("HEAD_UPSTREAM_MISMATCH")
    if require_final_match and final["status"]:
        errors.append("FINAL_WORKTREE_NOT_CLEAN")
    if not HEX40.fullmatch(final["head"]):
        errors.append("INVALID_HEAD_IDENTITY")

    return {
        "schema_version": GIT_CONVERGENCE_SCHEMA, "created_utc": now(), "valid": not errors,
        "errors": list(dict.fromkeys(errors)), "actions": actions,
        "initial": initial, "after_fetch": fetched, "after_commit": committed, "final": final,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--stage-all", action="store_true")
    ap.add_argument("--commit-message")
    ap.add_argument("--push", action="store_true")
    ns = ap.parse_args()
    result = run(ns.root, fetch=ns.fetch, stage_all=ns.stage_all, commit_message=ns.commit_message, push=ns.push, require_final_match=True)
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"valid": result["valid"], "errors": result["errors"], "actions": result["actions"], "final": result.get("final")}, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
