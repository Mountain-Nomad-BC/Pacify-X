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
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-incremental", action="store_true")
    parser.add_argument("--max-files", type=int, default=100_000)
    parser.add_argument("--max-depth", type=int, default=96)
    parser.add_argument("--max-bytes", type=int, default=2 * 1024 * 1024 * 1024)
    parser.add_argument("--max-text-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument(
        "--exclude-prefix",
        action="append",
        default=[],
        help="Repeatable project-relative path prefix to exclude before traversal.",
    )
    args = parser.parse_args(argv)
    print(
        json.dumps(
            build_project_map(
                args.project,
                output_dir=args.output_dir,
                max_files=args.max_files,
                max_depth=args.max_depth,
                max_bytes=args.max_bytes,
                max_text_bytes=args.max_text_bytes,
                incremental=not args.no_incremental,
                exclude_prefixes=args.exclude_prefix,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
