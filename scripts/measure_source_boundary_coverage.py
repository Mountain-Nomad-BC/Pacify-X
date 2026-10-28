"""Measure real generated-artifact boundary coverage for PX-GAP-0007.

Read-only. Compares what runtime/source_boundary.py classifies as generated
against what the repository actually contains that is machine-generated but not
yet declared, so coverage is measured rather than asserted.

The focus is the concrete candidates already identified in this recovery round:
the stale extension server bundle and the architecture atlas outputs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.source_boundary as sb  # noqa: E402

# Concrete machine-generated candidates observed live in this repository.
CANDIDATES = (
    "extension/server/index.js",
    "extension/server/source.mjs",
    "extension/package-lock.json",
    "docs/architecture/ATLAS_OFFLINE.html",
    "docs/architecture/graph_data.js",
    "docs/architecture/reference/graph_baseline_architecture.json",
)


def main() -> int:
    root = ROOT.resolve()
    declared = {getattr(item, "path", str(item)) for item in sb.GENERATED_ARTIFACTS}

    print("declared generated artifacts:")
    for item in sorted(declared):
        print(f"  {item}")
    print()

    print(f"{'path':62s} {'exists':7s} {'size':>10s}  classification")
    print("-" * 100)
    undeclared_present: list[str] = []
    for relative in CANDIDATES:
        path = root / relative
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
        classification = sb.classify_path(relative) if exists else "-"
        marker = ""
        covered = any(
            relative == item or relative.startswith(f"{item}/") for item in declared
        )
        if exists and not covered:
            marker = "  <-- UNDECLARED"
            undeclared_present.append(relative)
        print(
            f"{relative:62s} {str(exists):7s} {size:>10d}  {classification}{marker}"
        )

    print()
    census = sb.census(root)
    print("census by_classification:")
    for name, totals in sorted(census["by_classification"].items()):
        print(f"  {name:16s} files={totals['files']:6d} bytes={totals['bytes']:>12d}")
    print()
    print(f"undeclared machine-generated candidates present: {len(undeclared_present)}")
    for item in undeclared_present:
        print(f"  {item}")
    print()
    print(
        "json="
        + json.dumps(
            {
                "declared": sorted(declared),
                "undeclared_present": undeclared_present,
                "by_classification": census["by_classification"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())