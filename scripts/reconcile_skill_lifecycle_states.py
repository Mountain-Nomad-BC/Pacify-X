"""Synchronize specialty admission states across catalog, packages, and ledger."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


BLOCK = re.compile(r"(?ms)^\[\[skills\]\]\n.*?(?=^\[\[skills\]\]\n|\Z)")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def reconcile(root: Path) -> dict[str, object]:
    resolved = root.resolve()
    specialty_path = resolved / "registry" / "specialty_map.json"
    specialty = json.loads(specialty_path.read_text(encoding="utf-8"))
    states = {
        str(item["id"]): str(item["state"])
        for category in specialty["categories"]
        for item in category["specialties"]
    }
    specialty["candidate_count"] = len(states)
    specialty["active_candidate_count"] = sum(state == "active" for state in states.values())
    specialty["deferred_candidate_count"] = sum(state == "mapped_deferred" for state in states.values())
    _write_json(specialty_path, specialty)
    package_updates = []
    for skill_id, state in sorted(states.items()):
        path = resolved / "registry" / "skill_packages" / f"{skill_id}.json"
        if not path.is_file():
            raise ValueError(f"specialty package is missing: {skill_id}")
        package = json.loads(path.read_text(encoding="utf-8"))
        package["status"] = state
        _write_json(path, package)
        package_updates.append(skill_id)

    ledger_path = resolved / "registry" / "admission_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger_updates = []
    for record in ledger.get("records", ()):
        skill_id = str(record.get("id", ""))
        if skill_id in states:
            record["status"] = states[skill_id]
            ledger_updates.append(skill_id)
    _write_json(ledger_path, ledger)

    operational_path = resolved / "registry" / "operational_capabilities.json"
    operational = json.loads(operational_path.read_text(encoding="utf-8"))
    operational_updates = []
    for record in operational.get("capabilities", ()):
        skill_id = str(record.get("id", ""))
        if skill_id in states:
            record["status"] = states[skill_id]
            operational_updates.append(skill_id)
    _write_json(operational_path, operational)

    catalog_path = resolved / "registry" / "skill_catalog.toml"
    catalog_text = catalog_path.read_text(encoding="utf-8")
    catalog_updates = []
    rendered = []
    cursor = 0
    for match in BLOCK.finditer(catalog_text):
        rendered.append(catalog_text[cursor:match.start()])
        block = match.group(0)
        identity = re.search(r'(?m)^id = "([a-z0-9-]+)"$', block)
        if identity and identity.group(1) in states:
            skill_id = identity.group(1)
            block, count = re.subn(r'(?m)^status = "[^"]+"$', f'status = "{states[skill_id]}"', block, count=1)
            if count != 1:
                raise ValueError(f"catalog status is missing: {skill_id}")
            catalog_updates.append(skill_id)
        rendered.append(block)
        cursor = match.end()
    rendered.append(catalog_text[cursor:])
    catalog_path.write_text("".join(rendered), encoding="utf-8", newline="\n")
    if set(catalog_updates) != set(states):
        raise ValueError("not every specialty state was found in the skill catalog")
    return {
        "specialties": len(states),
        "active": sum(state == "active" for state in states.values()),
        "mapped_deferred": sum(state == "mapped_deferred" for state in states.values()),
        "packages_updated": len(package_updates),
        "ledger_updated": len(ledger_updates),
        "operational_updated": len(operational_updates),
        "catalog_updated": len(catalog_updates),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
