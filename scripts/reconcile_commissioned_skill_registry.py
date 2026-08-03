"""Reconcile the bootstrap-owned commissioned skill-hash projection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.commissioning import _skill_registry


def reconcile(root: Path, *, check: bool) -> dict[str, object]:
    root = root.resolve(); target = root / ".engineering-bootstrap/project-registry.json"
    current = json.loads(target.read_text(encoding="utf-8")); mode = current.get("mode", "existing")
    expected = json.loads(_skill_registry(root, str(mode)).decode("utf-8"))
    changed = [
        item["id"] for item in expected["skills"]
        if next((old for old in current.get("skills", []) if old.get("id") == item["id"]), None) != item
    ]
    stale_ids = sorted({item.get("id") for item in current.get("skills", [])} - {item["id"] for item in expected["skills"]})
    if (changed or stale_ids) and not check:
        target.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return {"schema_version": "1.0", "valid": not changed and not stale_ids if check else True, "changed": sorted(changed), "stale": stale_ids, "skill_count": len(expected["skills"]), "check": check}


def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=Path("."));parser.add_argument("--check",action="store_true")
    args=parser.parse_args();result=reconcile(args.root,check=args.check);print(json.dumps(result,indent=2));return 0 if result["valid"] else 1


if __name__=="__main__":raise SystemExit(main())
