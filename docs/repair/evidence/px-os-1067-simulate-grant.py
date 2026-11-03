"""PX-OS-1067 — what would a `reports/` output-root grant actually resolve?

The `reports/` grant was retired because no producer guaranteed writes beneath it. Before
granting anything, this replays the exact rule the classifier uses with a hypothetical
registry in memory. Nothing is written and no grant exists: this answers whether a grant
would be honest, and how many producers it would move.

Run:
    .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-simulate-grant.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from runtime.output_root_classification import _granted_destination  # noqa: E402
from runtime.output_root_classification import produced_destinations  # noqa: E402

CENSUS = Path(__file__).parent / "px-os-1067-census-2026-11-03.json"

HYPOTHETICAL = {
    "roots": {
        "reports": {
            "owner": "release",
            "granted_by": "owner",
            "granted_at": "2026-11-03",
            "retention": "run-scoped",
            "invocation_model": "caller",
        }
    },
    "grants": [],
}


def main() -> int:
    document = json.loads(CENSUS.read_text(encoding="utf-8"))
    unresolved = [path for path in document["unresolved_paths"] if path.startswith("scripts/")]

    qualified = []
    reasons: dict[str, int] = {}
    for relative in unresolved:
        destinations = produced_destinations(ROOT, relative)
        if not destinations:
            reasons["no_static_destination"] = reasons.get("no_static_destination", 0) + 1
            continue
        if all(_granted_destination(HYPOTHETICAL, destination, "9999-12-31T23:59:59Z") for destination in destinations):
            qualified.append(relative)
        else:
            reasons["ungranted_destination"] = reasons.get("ungranted_destination", 0) + 1

    result = {
        "schema_version": "px.output-grant-simulation/1.0",
        "gap_id": "PX-OS-1067",
        "hypothesis": {"root": "reports", "retention": "run-scoped"},
        "evaluated": len(unresolved),
        "would_resolve": len(qualified),
        "producers": qualified,
        "not_resolved": reasons,
        "writes_registry": False,
        "conclusion": (
            "A `reports/` grant would resolve "
            f"{len(qualified)} of {len(unresolved)} unresolved scripts producers under the "
            "all-destinations rule. The rest write somewhere else or nowhere statically "
            "visible, so granting `reports/` would leave them unresolved regardless."
        ),
    }
    (Path(__file__).parent / "px-os-1067-output-grant-simulation.json").write_text(
        json.dumps(result, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({k: result[k] for k in ("evaluated", "would_resolve", "not_resolved")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
