"""Portable command wrapper for governed specialist routing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[4]
if (SOURCE_ROOT / "runtime").is_dir() and str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from runtime.agent_provider import route_agents  # noqa: E402
from runtime.paths import framework_root  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task")
    parser.add_argument("--constraint", action="append", default=[])
    parser.add_argument("--max-reviewers", type=int, default=3)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    result = route_agents(
        args.root or framework_root(),
        args.task,
        constraints=args.constraint,
        max_reviewers=args.max_reviewers,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
