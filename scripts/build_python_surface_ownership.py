"""Build the hash-bound Python surface ownership and validation map."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.guarded_registry_projection import publish_guarded_registry_projection

from runtime.exact_tool_certification import certify_exact_tools  # noqa: E402
from runtime.python_surface_certification import certify_python_surfaces  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--admission-event-id", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (
        args.output or (root / "registry" / "python_surface_ownership.json")
    ).resolve()
    tools = certify_exact_tools(root)
    result = certify_python_surfaces(root, tools, require_map_current=False)
    # The bytes being written are the current map. Persist that authority fact,
    # not whether the prior on-disk projection happened to match.
    result["map_current"] = True
    publish_guarded_registry_projection(root, output.relative_to(root).as_posix(), result,
        admission_event_id=args.admission_event_id)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "valid",
                    "python_file_count",
                    "syntax_valid_count",
                    "packaged_file_count",
                    "direct_behavior_count",
                    "evidence_association_count",
                    "source_only_structural_count",
                    "errors",
                )
            },
            indent=2,
        )
    )
    return 0 if tools["valid"] and result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
