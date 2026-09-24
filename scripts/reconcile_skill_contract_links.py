"""Reconcile each native skill package's declared contract-link hash to its canonical bytes.

Found by the V3 discovery audit: 181 of 183 skill packages carried a stale
``contracts/manifest.json`` hash (and the same drift surfaced as 180 invalid contract links).

Root cause (not a product defect):

  ``scripts/migrate_px_skills.py`` records ``sha256 = _sha(registry/skill_packages/<id>.json)`` into
  ``.px/skills/<id>/contracts/manifest.json``. That manifest is written once, during migration, and
  the migration returns early when the target already exists -- so the declared digest is never
  refreshed afterwards. This campaign's capability-map reconciliation then rewrote the package
  files (settling ``body_sha256``, dependency edges, and the contract hash), which made every
  recorded link stale.

The correct repair is to recompute the declared digest from the canonical bytes, not to weaken the
check. The canonical bytes for a catalogue skill are ``registry/skill_packages/<id>.json``; for a
shared capability whose implementation is a package file, that file is the implementation.

Deterministic and non-mutating by default:

    python scripts/reconcile_skill_contract_links.py --root . --check
    python scripts/reconcile_skill_contract_links.py --root . --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tomllib
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LINK_SCHEMA = "px.skill-contract-links/1.0"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    encoded = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_text(encoded, encoding="utf-8", newline="\n")
    os.replace(prepared, path)


def _declared_contract(root: Path, skill_id: str, catalogue_row: dict) -> str | None:
    """The package file a skill's contract link should point at, from canonical inputs."""

    declared = str(catalogue_row.get("contract") or "")
    if declared:
        candidate = root / declared
        if candidate.is_file():
            return declared
    package = root / "registry" / "skill_packages" / f"{skill_id}.json"
    if package.is_file():
        return package.relative_to(root).as_posix()
    return None


def reconcile(root: Path, *, apply: bool) -> dict[str, object]:
    root = root.resolve(strict=True)
    catalogue = tomllib.loads(
        (root / "registry/skill_catalog.toml").read_text(encoding="utf-8")
    )
    rows = {
        str(s["id"]): s
        for s in catalogue.get("skills", [])
        if isinstance(s, dict) and "id" in s
    }

    checked = 0
    stale: list[dict[str, object]] = []
    fixed: list[str] = []
    no_contract: list[str] = []
    authored: list[dict[str, object]] = []

    skills_root = root / ".px" / "skills"
    if not skills_root.is_dir():
        return {
            "schema_version": "px.skill-contract-link-reconciliation/1.0",
            "valid": False,
            "errors": [".px/skills is missing"],
        }

    for skill_dir in sorted(d for d in skills_root.iterdir() if d.is_dir()):
        manifest_path = skill_dir / "contracts" / "manifest.json"
        if not manifest_path.is_file():
            continue
        checked += 1
        skill_id = skill_dir.name
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as error:
            stale.append(
                {"skill_id": skill_id, "reason": f"unparseable manifest: {error}"}
            )
            continue
        row = rows.get(skill_id)
        if row is None:
            no_contract.append(skill_id)
            continue

        declared_relative = _declared_contract(root, skill_id, row)
        if declared_relative is None:
            no_contract.append(skill_id)
            continue
        actual = _sha(root / declared_relative)

        contracts = manifest.get("contracts")
        if not isinstance(contracts, list) or not contracts:
            # A skill may carry an AUTHORED contract manifest instead of the migration-generated
            # `contracts[]` link shape (for example execution-placement-decision declares
            # runtime / decision_schema / promotion_schema / effects directly). That is a
            # legitimate alternative shape, not a stale link, so it is reported separately.
            authored.append({
                "skill_id": skill_id,
                "shape": sorted(key for key in manifest if key != "schema_version"),
            })
            continue
        record = contracts[0]
        if record.get("source") != declared_relative or record.get("sha256") != actual:
            stale.append(
                {
                    "skill_id": skill_id,
                    "declared_source": record.get("source"),
                    "declared_sha256": record.get("sha256"),
                    "canonical_source": declared_relative,
                    "canonical_sha256": actual,
                }
            )
            if apply:
                manifest["schema_version"] = LINK_SCHEMA
                manifest["contracts"] = [
                    {
                        "source": declared_relative,
                        "sha256": actual,
                        "available": True,
                    }
                ]
                _write_json(manifest_path, manifest)
                fixed.append(skill_id)

    return {
        "schema_version": "px.skill-contract-link-reconciliation/1.0",
        "valid": not stale or apply,
        "apply": apply,
        "checked": checked,
        "stale_count": len(stale),
        "fixed_count": len(fixed),
        "authored_contract_manifests": authored[:10],
        "stale": stale[:20],
        "skills_without_a_catalogue_contract": no_contract[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = reconcile(args.root, apply=args.apply and not args.check)
    print(json.dumps(result, indent=2))
    return 0 if (result["valid"] or result["stale_count"] == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
