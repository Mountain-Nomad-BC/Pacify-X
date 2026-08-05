"""Fail-closed public licensing and attribution validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any


AUTHOR = "Ben J. Cikovic"
PUBLISHER = "Mountain-Nomad-BC"
LICENSE_ID = "Apache-2.0"
OFFICIAL_APACHE_2_SHA256 = (
    "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
)
REPOSITORY = "https://github.com/Mountain-Nomad-BC/Pacify-X"
NOTICE_TEXT = """Engineering Loop and Bootstrap Orchestrations

Copyright © 2026
Ben J. Cikovic,
doing business as Mountain-Nomad-BC.

Originally designed and developed by
Ben J. Cikovic.

Published by the Mountain-Nomad-BC GitHub organization.

This project contains original engineering methodology,
AI orchestration architecture,
validation frameworks,
governance systems,
tooling,
automation patterns,
and supporting documentation.

Licensed under the Apache License, Version 2.0.
"""
REQUIRED_ROOT_FILES = {".gitignore", "CHANGELOG.md", "LICENSE", "MANIFEST.in", "NOTICE"}
THIRD_PARTY_LICENSES = {
    "LICENSES/everything-claude-code-MIT.txt": "Everything Claude Code",
    "LICENSES/mattpocock-skills-MIT.txt": "mattpocock/skills",
    "providers/agency_agents/LICENSE.txt": "AgentLand contributors",
}
CONFLICTING_PROJECT_LICENSES = {
    "LicenseRef-Proprietary",
    '"license": "Proprietary"',
    'license = "Proprietary"',
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_licensing(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    required = sorted(REQUIRED_ROOT_FILES)
    for name in required:
        if not (root / name).is_file():
            errors.append(f"missing publication file: {name}")

    license_path = root / "LICENSE"
    if license_path.is_file():
        text = license_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        markers = (
            "Apache License\n                           Version 2.0, January 2004",
            "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
            "1. Definitions.",
            "9. Accepting Warranty or Additional Liability.",
            "END OF TERMS AND CONDITIONS",
            "APPENDIX: How to apply the Apache License to your work.",
        )
        if len(text) < 11_000 or any(marker not in text for marker in markers):
            errors.append(
                "LICENSE is not the complete standard Apache License 2.0 text"
            )
        if _sha256(license_path) != OFFICIAL_APACHE_2_SHA256:
            errors.append(
                "LICENSE does not byte-match the official Apache License 2.0 text"
            )

    notice_path = root / "NOTICE"
    if notice_path.is_file():
        notice = notice_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if not notice.startswith(NOTICE_TEXT):
            errors.append(
                "NOTICE attribution does not match the governed publication identity"
            )
        for relative, marker in THIRD_PARTY_LICENSES.items():
            if not (root / relative).is_file():
                errors.append(f"missing third-party license: {relative}")
            elif marker not in notice:
                errors.append(f"NOTICE is missing third-party attribution: {marker}")

    pyproject_path = root / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]
        if project.get("license") != LICENSE_ID:
            errors.append(f"pyproject project.license must be {LICENSE_ID}")
        if AUTHOR not in {str(item.get("name")) for item in project.get("authors", ())}:
            errors.append(f"pyproject authors must include {AUTHOR}")
        urls = project.get("urls", {})
        if urls.get("Repository") != REPOSITORY or urls.get("Homepage") != REPOSITORY:
            errors.append("pyproject repository ownership metadata is inconsistent")
        if set(project.get("license-files", ())) != {"LICENSE", "NOTICE"}:
            errors.append("pyproject license-files must include LICENSE and NOTICE")
    except (OSError, KeyError, tomllib.TOMLDecodeError) as error:
        errors.append(f"invalid pyproject licensing metadata: {error}")

    owned_contracts = sorted((root / "registry" / "skills").glob("*.json"))
    for path in owned_contracts:
        try:
            if (
                json.loads(path.read_text(encoding="utf-8")).get("license")
                != LICENSE_ID
            ):
                errors.append(
                    f"owned skill contract license mismatch: {path.relative_to(root).as_posix()}"
                )
        except (OSError, json.JSONDecodeError) as error:
            errors.append(
                f"invalid owned skill contract: {path.relative_to(root).as_posix()}: {error}"
            )

    readme_path = root / "README.md"
    if readme_path.is_file():
        readme = readme_path.read_text(encoding="utf-8")
        for marker in (
            "## License",
            AUTHOR,
            "doing business as Mountain-Nomad-BC",
            "Apache License, Version 2.0",
        ):
            if marker not in readme:
                errors.append(f"README licensing attribution missing: {marker}")

    conflict_files = [pyproject_path, *owned_contracts]
    for path in conflict_files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for token in CONFLICTING_PROJECT_LICENSES:
            if token in text:
                errors.append(
                    f"conflicting project license token in {path.relative_to(root).as_posix()}: {token}"
                )

    policy_path = root / "policies" / "release-artifact-policy.json"
    try:
        roots = set(
            json.loads(policy_path.read_text(encoding="utf-8"))["product_root_files"]
        )
        missing_from_policy = sorted(REQUIRED_ROOT_FILES - roots)
        if missing_from_policy:
            errors.append(
                f"publication files absent from release artifact policy: {missing_from_policy}"
            )
    except (OSError, KeyError, json.JSONDecodeError) as error:
        errors.append(f"invalid release artifact policy: {error}")

    files = [
        path
        for path in (
            license_path,
            notice_path,
            pyproject_path,
            readme_path,
            policy_path,
        )
        if path.is_file()
    ]
    files.extend(path for path in owned_contracts if path.is_file())
    files.extend(
        root / relative
        for relative in THIRD_PARTY_LICENSES
        if (root / relative).is_file()
    )
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "license": LICENSE_ID,
        "author": AUTHOR,
        "publisher": PUBLISHER,
        "repository": REPOSITORY,
        "checked_file_count": len(files),
        "files": [
            {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}
            for path in sorted(files)
        ],
        "errors": errors,
    }


def write_licensing_report(
    root: Path, destination: Path | None = None
) -> dict[str, Any]:
    root = root.resolve()
    report = validate_licensing(root)
    target = destination or root / "evidence" / "licensing-consistency-report.json"
    target = target if target.is_absolute() else root / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {**report, "report": target.relative_to(root).as_posix()}
