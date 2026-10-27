"""Diagnose source reconciliation without copying files or refreshing projections.

Git supplies the source denominator. A worktree's .git pointer is metadata,
never an implementation to port. Inherited untracked source remains explicit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.repository_scope import is_external_environment_relative


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *arguments])


def source_paths(root: Path, *, untracked: bool = False) -> set[str]:
    arguments = ("ls-files", "--others", "--exclude-standard", "-z") if untracked else ("ls-files", "-z")
    return {name for name in git(root, *arguments).decode("utf-8").split("\0")
        if name and not is_external_environment_relative(name)
        and not name.startswith("docs/repair/evidence/")
        and name != ".git" and not name.startswith(".git/")}


def image(root: Path, name: str) -> tuple[bytes | None, str | None]:
    path = root / name
    if path.is_symlink():
        return None, "symlink_requires_review"
    if not path.is_file():
        return None, "missing_or_nonregular"
    if path.stat().st_size > 4 * 1024 * 1024:
        return None, "large_artifact_requires_separate_review"
    return path.read_bytes(), None


def digest(raw: bytes | None) -> str | None:
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def inventory(target: Path, source: Path) -> dict:
    tracked = source_paths(target)
    untracked = source_paths(target, untracked=True)
    candidates = source_paths(source)
    rows = []
    for name in sorted(tracked | untracked | candidates):
        target_raw, target_error = image(target, name)
        source_raw, source_error = image(source, name)
        if target_error == "large_artifact_requires_separate_review" or source_error == "large_artifact_requires_separate_review":
            state = "LARGE_ARTIFACT_RETAIN_FOR_SEPARATE_REVIEW"
        elif name not in candidates:
            state = "TARGET_ONLY_RETAIN_AND_REVIEW"
        elif target_raw is None:
            state = "SOURCE_ONLY_REVIEW_REQUIRED"
        elif source_raw is None:
            state = "SOURCE_MISSING_OR_LINK_REVIEW_REQUIRED"
        elif target_raw == source_raw:
            state = "EXACT_BYTES_EQUAL"
        else:
            state = "DIVERGENT_REQUIRES_SEMANTIC_REVIEW"
            try:
                left, right = (raw.decode("utf-8-sig").replace("\r\n", "\n") for raw in (target_raw, source_raw))
                if left == right:
                    state = "ENCODING_OR_LINE_ENDING_ONLY_REVIEW_REQUIRED"
                elif left == right.replace("agentic_engineering_os_px", "engineering-bootstrap"):
                    state = "NAMESPACE_ONLY_REVIEW_REQUIRED"
            except UnicodeError:
                pass
        rows.append({"path":name, "state":state,
            "target_tracking":"tracked" if name in tracked else "untracked" if name in untracked else "absent",
            "target_sha256":digest(target_raw), "source_sha256":digest(source_raw),
            "target_error":target_error, "source_error":source_error,
            "disposition":"UNREVIEWED" if state != "EXACT_BYTES_EQUAL" else "BYTE_COMPARISON_ONLY"})
    counts = {state:sum(row["state"] == state for row in rows) for state in sorted({row["state"] for row in rows})}
    assert not any(row["path"] == ".git" or row["path"].startswith((".git/", ".audit-handoff/")) for row in rows)
    return {"schema_version":"px.repair-reconciliation-inventory/1.0",
        "target":str(target), "source":str(source),
        "target_head":git(target,"rev-parse","HEAD").decode().strip(),
        "source_head":git(source,"rev-parse","HEAD").decode().strip(),
        "scope":"Git tracked plus target untracked source; canonical non-product custody excluded",
        "certification":False, "files_copied":0, "counts":counts, "rows":rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    result = inventory(options.target.resolve(strict=True), options.source.resolve(strict=True))
    with options.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"counts":result["counts"], "files_copied":0, "output":str(options.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
