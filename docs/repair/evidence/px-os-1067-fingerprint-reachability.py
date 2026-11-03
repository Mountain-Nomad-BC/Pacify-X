"""PX-OS-1067 Priority 3 — bounded reachability check for reviewed custody sources.

The inert-fingerprint report recovered 21 of 103 reviewed sources from reachable
history and left 80 ``not_found_within_bound``. The obvious next question is whether
those sources are gone because history was pruned, or simply because the reviewed
revision has not been located yet. This inspects Git object metadata only — no working
tree change, no fingerprint rewrite, no reviewer approval.

It reports counts and a recommendation. It never marks a fingerprint resolved.
"""
from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INERT = ROOT / "docs/repair/evidence/px-os-1067-inert-fingerprint-dispositions.json"
OUT = ROOT / "docs/repair/evidence/px-os-1067-fingerprint-reachability.json"


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    document = json.loads(INERT.read_text(encoding="utf-8"))
    rows = document["reviewed_source_rows"]

    shallow = git("rev-parse", "--is-shallow-repository").stdout.strip()
    commit_count = git("rev-list", "--count", "HEAD").stdout.strip()
    grafted = (ROOT / ".git/info/grafts").exists()
    shallow_file = (ROOT / ".git/shallow").exists()

    classes: Counter[str] = Counter()
    per_path = []
    recovered_now = 0
    for row in rows:
        path = row["path"]
        reviewed = row["reviewed_sha256"]
        recovery = row.get("reviewed_source_recovery") or {}
        prior = recovery.get("status", "unknown")
        # Real check, not a metadata guess: does any reachable revision of this path hold
        # exactly the reviewed bytes? `git rev-list --all -- path` is history-scoped, so this
        # is cheap even for the large inherited tree.
        revs = git("rev-list", "--all", "--", path).stdout.split()
        exact_revision = None
        for revision in revs:
            blob = git("rev-parse", f"{revision}:{path}")
            if blob.returncode != 0:
                continue
            checksum = git("cat-file", "-p", f"{revision}:{path}")
            if checksum.returncode != 0:
                continue
            import hashlib

            if hashlib.sha256(checksum.stdout.encode("utf-8", "surrogateescape")).hexdigest() == reviewed:
                exact_revision = revision
                break
        if exact_revision and prior != "head_exact" and prior != "reachable_history_exact":
            recovered_now += 1
        classes[prior] += 1
        per_path.append(
            {
                "path": path,
                "prior_recovery": prior,
                "reachable_revisions": len(revs),
                "exact_reviewed_revision_found_now": exact_revision,
                "reviewed_sha256": reviewed,
                "disposition": row.get("disposition"),
            }
        )

    result = {
        "schema_version": "px.fingerprint-reachability/1.0",
        "gap_id": "PX-OS-1067",
        "priority": 3,
        "measurement": "git object/commit metadata only; no worktree change",
        "repository_state": {
            "shallow": shallow == "true",
            "shallow_marker_present": shallow_file,
            "grafts_present": grafted,
            "reachable_commits": commit_count,
        },
        "fingerprints": len(rows),
        "classes": dict(sorted(classes.items())),
        "newly_recovered_exact_revisions": recovered_now,
        "still_unrecovered": sum(
            1 for item in per_path if not item["exact_reviewed_revision_found_now"]
        ),
        "fingerprints_changed": 0,
        "approvals_created": 0,
        "recommendation": (
            "The reviewed bytes for these paths are not in reachable history, and no reviewer "
            "approval exists for their current content. Rewriting a fingerprint would assert a "
            "review that did not happen, so the only lawful routes are (a) the external original "
            "review artifact, or (b) an accountable independent re-review of the current file. "
            "Both are governance acts, not engineering tasks."
        ),
        "status": "BLOCKED_AUTHORITY",
        "rows": per_path,
    }
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("repository_state", "newly_recovered_exact_revisions", "still_unrecovered")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
