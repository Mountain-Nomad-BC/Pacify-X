"""Build the deterministic local specialist-provider graph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.agent_provider import build_agent_graph  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--output", type=Path, default=Path("registry/agency_agent_graph.json")
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    rendered = json.dumps(build_agent_graph(root), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        valid = output.is_file() and output.read_text(encoding="utf-8") == rendered
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
        valid = True
    result = {"valid": valid, "output": output.relative_to(root).as_posix()}
    print(json.dumps(result, indent=2))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
