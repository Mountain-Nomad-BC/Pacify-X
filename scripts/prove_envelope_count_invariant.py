"""Prove the registry-envelope count invariant is real, not merely declared.

Creates an isolated copy of the registry, corrupts one declared count in each of
the three governed documents, and asserts the envelope validator rejects each
corruption. Nothing in the repository is modified: the copy is built in a
temporary directory and removed afterwards.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registry_envelope import validate_registry_envelopes  # noqa: E402

DOCUMENTS = (
    "registry/registry_envelope_inventory.json",
    "registry/plan_corpus.json",
    "registry/source_freeze.json",
    "registry/punch_card_ledger.json",
)

# (document, count field, key holding the value we corrupt)
CORRUPTIONS = (
    ("registry/plan_corpus.json", "archive_count", "archive_count"),
    ("registry/plan_corpus.json", "duplicate_payload_count", "duplicate_payload_count"),
    ("registry/source_freeze.json", "file_count", "file_count"),
    ("registry/source_freeze.json", "byte_count", "byte_count"),
    ("registry/punch_card_ledger.json", "card_count", "card_count"),
)


def _workspace(prefix: str):
    from runtime.resource_lifecycle import ResourceManager

    manager = ResourceManager(ROOT / ".agentic_engineering_os_px/resource-lifecycle/ledger.json")
    record = manager.create_workspace(Path(tempfile.gettempdir()), project_id="pacify-x",
        run_id=prefix + uuid4().hex, lane_id="current-diagnostic",
        creator=__name__, prefix=prefix)
    return manager, record, Path(record.path)


def _close_workspace(manager, record):
    receipt = manager.reclaim_ephemeral_path(record.resource_id, reason="current_diagnostic_complete")
    if receipt.errors or receipt.resources_reclaimed != 1:
        raise RuntimeError("diagnostic workspace closure failed: " + repr(receipt.errors))


def stage(workspace: Path) -> Path:
    """Copy the whole registry tree plus every builder/consumer the inventory names."""
    root = workspace / "framework"
    shutil.copytree(ROOT / "registry", root / "registry")
    inventory = json.loads(
        (root / "registry/registry_envelope_inventory.json").read_text(encoding="utf-8")
    )
    for record in inventory["records"]:
        for role in ("builder", "consumer"):
            relative = record.get(role)
            if not relative:
                continue
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes((ROOT / relative).read_bytes())
    return root


def main() -> int:
    failures: list[str] = []
    inventory = json.loads((ROOT / "registry/registry_envelope_inventory.json").read_text(encoding="utf-8"))
    if (ROOT / "policies/rev1xx-validation.json").is_file():
        corruptions = [(record["path"], record["count_key"], record["count_key"])
                       for record in inventory["records"]
                       if record["path"].startswith(("registry/planning/rev1xx/", "registry/source-freeze/current-campaign/"))
                       or record["path"] == "registry/punch_card_ledger.json"]
        if not corruptions:
            raise ValueError("current campaign has no admitted count owners to prove")
    else:
        corruptions = CORRUPTIONS

    baseline_manager, baseline_record, baseline_workspace = _workspace("px-env-base-")
    try:
        root = stage(baseline_workspace)
        baseline = validate_registry_envelopes(root)
        print(f"baseline valid={baseline['valid']}")
        for error in baseline["errors"]:
            print(f"  - {error}")
        if not baseline["valid"]:
            failures.append(
                "staged baseline must be valid for the negative checks to be meaningful: "
                + "; ".join(baseline["errors"])
            )
    finally:
        _close_workspace(baseline_manager, baseline_record)

    print()
    print("negative checks (each declared count must be rejected when corrupted):")
    for relative, field, key in corruptions:
        manager, record, workspace = _workspace("px-env-neg-")
        try:
            root = stage(workspace)
            path = root / relative
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(payload.get(key), int), f"{relative}/{key} is not an integer"
            original = payload[key]
            payload[key] = original + 7
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            report = validate_registry_envelopes(root)
            rejected = any(field in error for error in report["errors"])
            print(
                f"  {'REJECTED' if rejected else 'ACCEPTED'}  "
                f"{relative}/{field} ({original} -> {original + 7})"
            )
            if not rejected:
                failures.append(f"{relative}/{field}: corruption was NOT detected")
        finally:
            _close_workspace(manager, record)

    print()
    if failures:
        print("INVARIANT NOT PROVEN:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"OK: all {len(corruptions)} selected current campaign count fields reject corruption.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
