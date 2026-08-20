from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from runtime.project_map_retrieval import query_project_map


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            query_project_map(args.project, args.query, top_k=args.top_k),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
