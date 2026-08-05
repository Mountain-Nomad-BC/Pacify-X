from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from runtime.project_intelligence import build_project_map


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--no-incremental", action="store_true")
    args = parser.parse_args(argv)
    print(
        json.dumps(
            build_project_map(args.project, incremental=not args.no_incremental),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
