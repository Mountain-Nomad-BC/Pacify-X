"""Search both candidate trees for every item this project is currently missing.

Read-only. For each item, report presence, size and a content fingerprint so the
report can distinguish "found the real thing" from "found a same-named stub".
"""
import hashlib
import json
from pathlib import Path

TREES = {
    "MUSIC": Path(r"C:\Users\Ben\Music\Pacify-X-main\Pacify-X-main"),
    "VIDEOS": Path(r"C:\Users\Ben\Videos\Pacify-X-main"),
}
CANONICAL = Path(r"C:\Users\Ben\Documents\bootstrap_project\Pacify-X")

ITEMS = [
    # (label, relative path, what we need it for)
    ("T.I.E. fusion owner", "runtime/usage_memory.py", "fuse_tie_experience reference"),
    ("T.I.E. caller", "runtime/model_group_preparation.py", "tie_bindings path"),
    ("semantic entity owner", "runtime/semantic_entity.py", "contract resolution"),
    ("semantic entity contract", "contracts/semantic/semantic-entity.schema.json", "missing contract"),
    ("semantic locator contract", "contracts/semantic/locator-record.schema.json", "reference-only"),
    ("ownership generator", "scripts/build_contract_ownership_registry.py", "source-authentic owners"),
    ("succession contracts", "contracts/project_revision_succession/active-revision.schema.json", "packaging"),
    ("succession owner", "runtime/project_revision_succession.py", "project_id gate"),
    ("DurableBudgetState", "extension/src/agentHarness/durableTaskState.js", "Node billing"),
    ("rollout compare_trees", "scripts/rollout/compare_trees.py", "source inventory"),
    ("rollout integration_plan", "scripts/rollout/integration_plan.py", "overlay plan"),
    ("rollout inventory test", "tests/test_rollout_inventory.py", "required suite"),
    ("billing settlement test", "extension/tests/billing-settlement-audit.test.js", "required suite"),
    ("studio experience", "runtime/usage_memory.py", "retrieve_studio_experience"),
]


def digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return "unreadable"


print(f"{'item':<28} {'path':<58} {'MUSIC':<12} {'VIDEOS':<12} {'CANONICAL':<12}")
print("-" * 124)
rows = []
for label, rel, purpose in ITEMS:
    cells = {}
    for name, root in list(TREES.items()) + [("CANONICAL", CANONICAL)]:
        target = root / rel
        if target.is_file():
            cells[name] = f"{target.stat().st_size}:{digest(target)}"
        else:
            cells[name] = "ABSENT"
    print(f"{label:<28} {rel:<58} {cells['MUSIC']:<12} {cells['VIDEOS']:<12} {cells['CANONICAL']:<12}")
    rows.append({"label": label, "path": rel, "purpose": purpose, **cells})

(out := Path(".tmp/resume9/tree_scan.json")).write_text(json.dumps(rows, indent=2), encoding="utf-8")
print(f"\nwrote {out}")
