"""Build a read-only SHA-256/Git identity manifest for the pre-cert baseline."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.pre_cert_contract import (  # noqa: E402
    EXECUTION_PATCH_FILES,
    HASH_MANIFEST_SCHEMA,
    REQUIRED_CERT_ROOT_DEPENDENCIES,
    REQUIRED_REPO_ROOT_DEPENDENCIES,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git(root: Path, *args: str, binary: bool = False, optional_locks: bool = True) -> str | bytes:
    env = dict(os.environ)
    if optional_locks:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    cp = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True,
        text=not binary, encoding=None if binary else "utf-8",
        errors=None if binary else "replace", check=False, timeout=120, env=env,
    )
    if cp.returncode != 0:
        out = cp.stderr if cp.stderr else cp.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        raise RuntimeError(f"git {' '.join(args)} failed: {str(out).strip()}")
    return cp.stdout


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def zpaths(value: bytes) -> list[str]:
    return [p.decode("utf-8", "surrogateescape") for p in value.split(b"\0") if p]


def path_record(root: Path, rel: str, *, tracked: bool, untracked: bool) -> dict[str, Any]:
    p = root / rel
    st = p.lstat()
    mode = stat.S_IFMT(st.st_mode)
    if stat.S_ISLNK(mode):
        target = os.readlink(p)
        return {
            "path": rel.replace("\\", "/"), "kind": "symlink", "size": len(target.encode("utf-8")),
            "sha256": sha256_text(target), "target": target,
            "tracked": tracked, "untracked": untracked,
        }
    if stat.S_ISREG(mode):
        return {
            "path": rel.replace("\\", "/"), "kind": "file", "size": st.st_size,
            "sha256": sha256_file(p), "mtime_ns": st.st_mtime_ns,
            "tracked": tracked, "untracked": untracked,
        }
    return {
        "path": rel.replace("\\", "/"), "kind": "unsupported", "size": st.st_size,
        "tracked": tracked, "untracked": untracked,
    }


def canonical_digest(records: list[dict[str, Any]]) -> str:
    stable = [
        {k: r[k] for k in ("path", "kind", "size", "sha256", "target") if k in r}
        for r in sorted(records, key=lambda x: x["path"].casefold())
    ]
    raw = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build(root: Path) -> dict[str, Any]:
    root = root.resolve()
    cert_root = Path(__file__).resolve().parents[1]
    tracked = set(zpaths(git(root, "ls-files", "-z", binary=True)))
    untracked = set(zpaths(git(root, "ls-files", "-z", "--others", "--exclude-standard", binary=True)))
    paths = sorted(tracked | untracked, key=str.casefold)
    records = [path_record(root, p, tracked=p in tracked, untracked=p in untracked) for p in paths if os.path.lexists(root / p)]

    head = str(git(root, "rev-parse", "HEAD")).strip()
    tree = str(git(root, "rev-parse", "HEAD^{tree}")).strip()
    branch = str(git(root, "branch", "--show-current")).strip()
    status = str(git(root, "status", "--porcelain=v2", "--branch", "--untracked-files=all"))
    try:
        upstream = str(git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")).strip()
        upstream_head = str(git(root, "rev-parse", "@{u}")).strip()
    except Exception:
        upstream = None
        upstream_head = None

    execution_patch = set(EXECUTION_PATCH_FILES)
    production_dependencies = tuple(
        p for p in REQUIRED_CERT_ROOT_DEPENDENCIES if p not in execution_patch
    )

    missing_patch = [p for p in EXECUTION_PATCH_FILES if not (cert_root / p).is_file()]
    missing_production_dependencies = [
        p for p in production_dependencies if not (root / p).is_file()
    ]
    missing_repo_dependencies = [
        p for p in REQUIRED_REPO_ROOT_DEPENDENCIES if not (root / p).is_file()
    ]
    missing_dependencies = (
        [f"cert:{p}" for p in missing_patch]
        + [f"repo:{p}" for p in missing_production_dependencies]
        + [f"repo:{p}" for p in missing_repo_dependencies]
    )
    unsupported = [r["path"] for r in records if r["kind"] == "unsupported"]

    return {
        "schema_version": HASH_MANIFEST_SCHEMA,
        "created_utc": now(),
        "root": str(root),
        "cert_root": str(cert_root),
        "git": {
            "branch": branch, "head": head, "tree": tree,
            "upstream": upstream, "upstream_head": upstream_head,
            "status_porcelain_v2": status.splitlines(),
        },
        "counts": {
            "tracked": len(tracked), "untracked_nonignored": len(untracked), "manifest_records": len(records),
        },
        "tracked_content_sha256": canonical_digest([r for r in records if r["tracked"]]),
        "admitted_worktree_content_sha256": canonical_digest(records),
        "execution_patch_missing": missing_patch,
        "required_dependency_missing": missing_dependencies,
        "unsupported_paths": unsupported,
        "valid_structure": not missing_patch and not missing_dependencies and not unsupported,
        "files": records,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--output", type=Path, required=True)
    ns = ap.parse_args()
    result = build(ns.root)
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("schema_version", "root", "counts", "tracked_content_sha256", "admitted_worktree_content_sha256", "valid_structure")}, indent=2))
    return 0 if result["valid_structure"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
