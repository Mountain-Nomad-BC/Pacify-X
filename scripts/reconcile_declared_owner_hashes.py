"""Reconcile declared-capability owner hashes without changing routing authority."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def reconcile(root: Path, *, check: bool) -> dict[str, object]:
    root = root.resolve()
    target = root / "registry/declared_capability_recovery_map.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    changed: list[str] = []
    errors: list[str] = []
    for record in payload.get("records", ()):
        owner = str(record.get("canonical_owner", ""))
        source_id = str(record.get("source_id", ""))
        body = root / ".px" / "skills" / owner / "SKILL.md"
        if not body.is_file():
            errors.append(f"{source_id}: owner body missing: {owner}")
            continue
        expected = hashlib.sha256(body.read_bytes()).hexdigest()
        if record.get("owner_body_sha256") != expected:
            record["owner_body_sha256"] = expected
            changed.append(source_id)
        if record.get("source_body_state") == "exact_authoritative_recovery":
            expected_state = {
                "coverage_state": "authoritative_implementation_verified",
                "historical_validation_state": "supplied_and_revalidated",
                "source_state": "authoritative",
            }
            if any(record.get(key) != value for key, value in expected_state.items()):
                record.update(expected_state)
                if source_id not in changed:
                    changed.append(source_id)
    valid = not errors and (not check or not changed)
    if changed and not check and not errors:
        target.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        valid = True
    return {
        "valid": valid,
        "record_count": len(payload.get("records", ())),
        "changed_count": len(changed),
        "changed": sorted(changed),
        "errors": errors,
        "check": check,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = reconcile(args.root, check=args.check)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
