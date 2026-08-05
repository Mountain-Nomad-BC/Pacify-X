"""Apply stable local identifiers to the shipped contract corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def normalize(root: Path) -> int:
    changed = 0
    for path in sorted((root / "contracts").rglob("*.json")):
        relative = path.relative_to(root).as_posix()
        expected = f"urn:engineering-loop-bootstrap:contract:{relative.removeprefix('contracts/').removesuffix('.schema.json').replace('/', ':')}"
        schema = json.loads(path.read_text(encoding="utf-8"))
        if schema.get("$id") == expected:
            continue
        schema_declaration = schema.pop("$schema")
        schema.pop("$id", None)
        normalized = {"$schema": schema_declaration, "$id": expected, **schema}
        path.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        changed += 1
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps({"changed": normalize(args.root.resolve())}))
