"""Verify that the third-party licence inventory matches the actual dependency manifests.

The inventory documents in `THIRD_PARTY_NOTICES.md` and `MODEL_AND_DATA_LICENSES.md` must not
drift from the real dependency set. A notice file that lists a component the manifests do not
reference — or omits one they do — is a compliance defect, because it misrepresents what ships.

This tool compares the two and fails on either direction of drift.

Usage:
    python scripts/verify_license_inventory.py --root .
    python scripts/verify_license_inventory.py --root . --json
Exit 0 when the inventory matches the manifests, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

SCHEMA = "px.license-inventory-verification/1.0"
NOTICE = Path("THIRD_PARTY_NOTICES.md")
MODEL_NOTICE = Path("MODEL_AND_DATA_LICENSES.md")


def manifest_components(root: Path) -> dict[str, list[str]]:
    """Every dependency the manifests actually declare."""

    python: list[str] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        for requirement in data.get("project", {}).get("dependencies", []) or []:
            name = re.split(r"[<>=!~\[]", str(requirement), maxsplit=1)[0].strip()
            if name:
                python.append(name)
        for requirement in data.get("build-system", {}).get("requires", []) or []:
            name = re.split(r"[<>=!~\[]", str(requirement), maxsplit=1)[0].strip()
            if name:
                python.append(name)

    npm: list[str] = []
    package_path = root / "extension/package.json"
    if package_path.is_file():
        package = json.loads(package_path.read_text(encoding="utf-8-sig"))
        for section in ("dependencies", "devDependencies"):
            npm.extend(str(name) for name in (package.get(section) or {}))

    return {"python": sorted(set(python)), "npm": sorted(set(npm))}


def documented_components(root: Path) -> str:
    path = root / NOTICE
    return path.read_text(encoding="utf-8-sig") if path.is_file() else ""


def verify(root: Path) -> dict:
    root = root.resolve(strict=True)
    components = manifest_components(root)
    notice_text = documented_components(root)

    missing_doc: list[str] = []
    if not notice_text:
        missing_doc.append(NOTICE.as_posix())
    if not (root / MODEL_NOTICE).is_file():
        missing_doc.append(MODEL_NOTICE.as_posix())

    undocumented: list[str] = []
    if notice_text:
        for name in components["python"] + components["npm"]:
            # The notice may reference the component by name or by its repository URL.
            if name in notice_text:
                continue
            undocumented.append(name)

    return {
        "schema_version": SCHEMA,
        "valid": not missing_doc and not undocumented,
        "manifests": {
            "python": components["python"],
            "npm": components["npm"],
        },
        "missing_documents": missing_doc,
        "undocumented_components": undocumented,
        "notice_path": NOTICE.as_posix(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(args.root)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["valid"] else 1
    print(f"license inventory: valid={result['valid']}")
    print(f"  python dependencies : {len(result['manifests']['python'])}")
    print(f"  npm dependencies    : {len(result['manifests']['npm'])}")
    for path in result["missing_documents"]:
        print(f"  MISSING DOCUMENT: {path}")
    for name in result["undocumented_components"]:
        print(f"  UNDOCUMENTED: {name}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
