from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.integration_disposition import (
    build_canonical_owner_index,
    build_source_disposition,
    validate_source_disposition,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-alias", required=True)
    parser.add_argument("--expected-tree-sha256")
    parser.add_argument("--owner-output", type=Path, required=True)
    parser.add_argument("--disposition-output", type=Path, required=True)
    args = parser.parse_args()
    owners = build_canonical_owner_index(args.root)
    dispositions = build_source_disposition(
        args.root,
        args.source,
        source_alias=args.source_alias,
        expected_tree_sha256=args.expected_tree_sha256,
    )
    validation = validate_source_disposition(dispositions)
    if not validation["valid"]:
        print(json.dumps(validation, indent=2))
        return 1
    args.owner_output.parent.mkdir(parents=True, exist_ok=True)
    args.disposition_output.parent.mkdir(parents=True, exist_ok=True)
    args.owner_output.write_text(json.dumps(owners, indent=2) + "\n", encoding="utf-8")
    args.disposition_output.write_text(
        json.dumps(dispositions, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "valid": True,
                "owner_records": owners["record_count"],
                "source_files": dispositions["file_count"],
                "unaccounted": dispositions["unaccounted_count"],
                "dispositions": dispositions["disposition_counts"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
