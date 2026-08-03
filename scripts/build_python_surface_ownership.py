"""Build the hash-bound Python surface ownership and validation map."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.exact_tool_certification import certify_exact_tools  # noqa: E402
from runtime.python_surface_certification import certify_python_surfaces  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output or (root / "registry" / "python_surface_ownership.json")).resolve()
    tools = certify_exact_tools(root)
    result = certify_python_surfaces(root, tools, require_map_current=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: result[key] for key in ("valid", "python_file_count", "syntax_valid_count", "packaged_file_count", "direct_behavior_count", "direct_test_reference_count", "source_only_structural_count", "errors")}, indent=2))
    return 0 if tools["valid"] and result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
