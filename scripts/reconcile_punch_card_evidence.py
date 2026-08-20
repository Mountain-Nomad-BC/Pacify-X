"""Check or refresh artifact hashes in current punch-card acceptance records."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


SCHEMA = "px.punch-card-evidence/1.0"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconcile(root: Path, *, apply: bool = False) -> dict[str, object]:
    root = root.resolve(strict=True)
    evidence_root = root / "evidence" / "punch-cards"
    changed: list[str] = []
    errors: list[str] = []
    checked = 0
    for path in sorted(evidence_root.glob("*.json"), key=lambda item: item.name):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{path.name}: unreadable: {error}")
            continue
        modern = record.get("schema_version") == SCHEMA
        legacy = record.get("schema_version") == "1.0" and record.get("accepted") is True
        if record.get("schema_version") == "1.0" and record.get("accepted") is False:
            continue
        if not modern and not legacy:
            errors.append(f"{path.name}: unsupported schema")
            continue
        if modern and record.get("status") != "accepted":
            continue
        dirty = False
        artifacts = record.get("artifacts", ())
        rows = (
            list(artifacts.items())
            if legacy and isinstance(artifacts, dict)
            else [
                (artifact.get("path"), artifact.get("sha256"))
                for artifact in artifacts
                if isinstance(artifact, dict)
            ]
            if isinstance(artifacts, list)
            else []
        )
        for relative, expected in rows:
            if not isinstance(relative, str) or not relative:
                errors.append(f"{path.name}: invalid artifact path")
                continue
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                errors.append(f"{path.name}: artifact escapes root: {relative}")
                continue
            if not target.is_file():
                errors.append(f"{path.name}: artifact missing: {relative}")
                continue
            checked += 1
            digest = _sha(target)
            if expected != digest:
                if legacy:
                    artifacts[relative] = digest
                else:
                    next(
                        item for item in artifacts
                        if isinstance(item, dict) and item.get("path") == relative
                    )["sha256"] = digest
                dirty = True
        if dirty:
            changed.append(path.name)
            if apply and not errors:
                timestamp = datetime.now(timezone.utc).isoformat()
                record["recorded_at" if modern else "created_utc"] = timestamp
                path.write_text(
                    json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
    return {
        "schema_version": "px.punch-card-reconciliation/1.0",
        "valid": not errors and (apply or not changed),
        "apply": apply,
        "accepted_record_count": len(list(evidence_root.glob("*.json"))),
        "artifact_count": checked,
        "changed": changed,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = reconcile(args.root, apply=args.apply)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
