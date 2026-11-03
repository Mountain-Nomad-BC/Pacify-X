"""PX-OS-1067 — choose the custodian by capability, never by filename.

The reconciled projection is the resource's canonical writer; `runtime/world_state.py`
*derives* a read-only view of it and is not the reconciling authority. So the criterion is
capability, established from source:

* a candidate that **writes outside the group** is the reconciler (it maintains canonical
  state);
* a candidate that only **reads** is a derived projection and can never be the owner;
* multiple writers outside the group → undecidable, stays pending.

Run:
    .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-break-ties.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if not (ROOT / "runtime").is_dir():
    ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.effect_surface import discover_effect_surfaces  # noqa: E402

REGISTRY = ROOT / "registry/runtime_state_ownership.json"


def choose(group: list[str], readers: list[str], writes: dict[str, set[str]]) -> tuple[str | None, str]:
    component = [r for r in readers if r.replace("\\", "/").endswith(".py")]
    if not component:
        return None, "no executable component outside the producer group"
    outside_writers = [r for r in component if writes.get(r)]
    inside_writers = [r for r in group if writes.get(r)]
    if outside_writers:
        if len(outside_writers) == 1:
            return outside_writers[0], "component outside the group writes canonical state"
        return None, (
            f"{len(outside_writers)} components outside the group write state; the "
            "reconciling authority is undecidable from source"
        )
    if inside_writers:
        return None, (
            "the only writer of this state is inside the producer group — the reconciled "
            "projection is maintained by a group member and no outside component writes it"
        )
    if len(component) == 1:
        return component[0], "sole outside component reader; state has no other writer"
    return None, f"{len(component)} read-only components outside the group and no writer"


def main() -> int:
    records = discover_effect_surfaces(ROOT)
    writes: dict[str, set[str]] = {}
    for record in records:
        if record["effect"] == "filesystem_mutation":
            writes.setdefault(record["path"], set()).add(str(record["line"]))

    document = json.loads(REGISTRY.read_text(encoding="utf-8"))
    changed = 0
    for item in document["resources"]:
        if item["registration_state"] == "pending_decision":
            continue
        group = item["group_members"]
        readers = item.get("outside_readers") or []
        owner, reason = choose(group, readers, writes)
        previous = item["record"].get("accountable_owner")
        if owner is None:
            item["record"]["accountable_owner"] = None
            item["record"]["owner_approval_event_id"] = None
            item["registration_state"] = "pending_registration"
            item["registration_reason"] = reason
            item.pop("custody_basis", None)
        else:
            item["record"]["accountable_owner"] = owner
            item["record"]["owner_approval_event_id"] = (
                "gap-event:PX-OPERATIONAL-GAPS-20260816:000000036534"
            )
            item["registration_state"] = "registered"
            item["registration_reason"] = None
            item["custody_basis"] = reason
        if previous != owner:
            changed += 1

    document["totals"] = {
        "resources": len(document["resources"]),
        "registered": sum(1 for i in document["resources"] if i["registration_state"] == "registered"),
        "pending_registration": sum(
            1 for i in document["resources"] if i["registration_state"] == "pending_registration"
        ),
        "pending_decision": sum(
            1 for i in document["resources"] if i["registration_state"] == "pending_decision"
        ),
    }
    REGISTRY.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(document["totals"]))
    print("changed:", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
