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


MAX_LICENSING_FILE_BYTES = 1024 * 1024
MAX_LICENSING_CORPUS_BYTES = 16 * 1024 * 1024
MAX_LICENSING_FILES = 4096
MAX_LICENSING_DIRECTORY_ENTRIES = 8192
MAX_LICENSING_REPORT_BYTES = 8 * 1024 * 1024


def _sha256(path: Path) -> str:
    from .input_files import independent_file, cooperative_deadline, read_file_image

    deadline = cooperative_deadline()
    checked, info = independent_file(path)
    image = read_file_image(
        checked, info, limit=MAX_LICENSING_FILE_BYTES, deadline=deadline
    )
    return hashlib.sha256(image).hexdigest()


def _licensing_corpus(root: Path):
    from .archive_io import member_identity, reject_path_links
    from .input_files import (
        contained_file,
        cooperative_deadline,
        check_deadline,
        read_file_image,
    )
    from .studio_filesystem import bounded_directory_entries

    deadline = cooperative_deadline()
    bodies = {
        "LICENSE",
        "NOTICE",
        "pyproject.toml",
        "README.md",
        "policies/release-artifact-policy.json",
        *THIRD_PARTY_LICENSES,
    }
    present = {}
    metadata = {}
    identities = set()
    total = 0

    def select(relative, *, body, required_selection=False):
        nonlocal total
        check_deadline(deadline)
        identity = member_identity(relative, allow_directory=False)
        if identity in identities:
            raise ValueError("licensing source paths alias one portable identity")
        identities.add(identity)
        try:
            path, info = contained_file(root, relative)
        except FileNotFoundError:
            if required_selection:
                raise ValueError("selected licensing input disappeared") from None
            present[relative] = False
            return
        present[relative] = True
        if body:
            if (
                len(metadata) >= MAX_LICENSING_FILES
                or info.st_size > MAX_LICENSING_FILE_BYTES
            ):
                raise ValueError(
                    "licensing input count or byte budget exhausted before acquisition"
                )
            total += info.st_size
            if total > MAX_LICENSING_CORPUS_BYTES:
                raise ValueError(
                    "licensing corpus byte budget exhausted before acquisition"
                )
            metadata[relative] = (path, info)

    for relative in sorted(bodies | REQUIRED_ROOT_FILES):
        select(relative, body=relative in bodies)
    directory = root / "registry/skills"
    reject_path_links(directory)
    contracts = []
    if directory.exists():
        if not directory.is_dir():
            raise ValueError("owned contract location must be a directory")
        entries = bounded_directory_entries(
            directory,
            MAX_LICENSING_DIRECTORY_ENTRIES,
            lambda: ValueError("licensing directory entry limit exceeded"),
        )
        check_deadline(deadline)
        for path in entries:
            if path.match("*.json"):
                relative = path.relative_to(root).as_posix()
                select(relative, body=True, required_selection=True)
                contracts.append(relative)
    images = {}
    for relative, (path, info) in metadata.items():
        images[relative] = bytes(
            read_file_image(
                path, info, limit=MAX_LICENSING_FILE_BYTES, deadline=deadline
            )
        )
    return present, images, contracts


def _licensing_text(raw: bytes) -> str:
    return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _licensing_object(raw: bytes) -> dict:
    from .json_io import decode_json_object

    return decode_json_object(
        raw, max_bytes=MAX_LICENSING_FILE_BYTES, max_depth=32, max_nodes=100000
    )


def _licensing_names(value: object, label: str, maximum: int) -> list[str]:
    from .numeric_inputs import bounded_text

    if type(value) is not list or len(value) > maximum:
        raise ValueError(f"{label} must be a bounded actual list")
    names = [bounded_text(item, label, maximum=4096, strip=False) for item in value]
    if len(set(names)) != len(names):
        raise ValueError(f"{label} must not contain duplicates")
    return names


def validate_licensing(root: Path) -> dict[str, Any]:
    from .input_files import directory_root
    from .numeric_inputs import bounded_text, bounded_json_value

    base = {
        "schema_version": "1.0",
        "license": LICENSE_ID,
        "author": AUTHOR,
        "publisher": PUBLISHER,
        "repository": REPOSITORY,
    }
    try:
        root = directory_root(root)
        present, images, contracts = _licensing_corpus(root)
        errors = []
        error_count = 0

        def error(message):
            nonlocal error_count
            error_count += 1
            if len(errors) < 256:
                errors.append(message)

        for name in sorted(REQUIRED_ROOT_FILES):
            if not present[name]:
                error(f"missing publication file: {name}")
        if present["LICENSE"]:
            text = _licensing_text(images["LICENSE"])
            markers = (
                "Apache License\n                           Version 2.0, January 2004",
                "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
                "1. Definitions.",
                "9. Accepting Warranty or Additional Liability.",
                "END OF TERMS AND CONDITIONS",
                "APPENDIX: How to apply the Apache License to your work.",
            )
            if len(text) < 11000 or any(marker not in text for marker in markers):
                error("LICENSE is not the complete standard Apache License 2.0 text")
            if (
                hashlib.sha256(images["LICENSE"]).hexdigest()
                != OFFICIAL_APACHE_2_SHA256
            ):
                error(
                    "LICENSE does not byte-match the official Apache License 2.0 text"
                )
        if present["NOTICE"]:
            notice = _licensing_text(images["NOTICE"])
            if not notice.startswith(NOTICE_TEXT):
                error(
                    "NOTICE attribution does not match the governed publication identity"
                )
            for relative, marker in THIRD_PARTY_LICENSES.items():
                if not present[relative]:
                    error(f"missing third-party license: {relative}")
                elif marker not in notice:
                    error(f"NOTICE is missing third-party attribution: {marker}")
        if not present["pyproject.toml"]:
            error("invalid pyproject licensing metadata: file is missing")
        else:
            project = tomllib.loads(_licensing_text(images["pyproject.toml"])).get(
                "project"
            )
            if type(project) is not dict:
                raise ValueError("pyproject must have an actual project table")
            if project.get("license") != LICENSE_ID:
                error(f"pyproject project.license must be {LICENSE_ID}")
            authors = project.get("authors", [])
            if (
                type(authors) is not list
                or len(authors) > 256
                or any(type(a) is not dict for a in authors)
            ):
                raise ValueError("project authors must be bounded actual records")
            names = {
                bounded_text(a.get("name"), "author name", maximum=256, strip=False)
                for a in authors
            }
            if AUTHOR not in names:
                error(f"pyproject authors must include {AUTHOR}")
            urls = project.get("urls", {})
            if type(urls) is not dict or len(urls) > 256:
                raise ValueError("project URLs must be a bounded actual table")
            if (
                urls.get("Repository") != REPOSITORY
                or urls.get("Homepage") != REPOSITORY
            ):
                error("pyproject repository ownership metadata is inconsistent")
            if set(
                _licensing_names(project.get("license-files", []), "license files", 64)
            ) != {"LICENSE", "NOTICE"}:
                error("pyproject license-files must include LICENSE and NOTICE")
        for relative in contracts:
            if _licensing_object(images[relative]).get("license") != LICENSE_ID:
                error(f"owned skill contract license mismatch: {relative}")
        if present["README.md"]:
            readme = _licensing_text(images["README.md"])
            for marker in (
                "## License",
                AUTHOR,
                "doing business as Mountain-Nomad-BC",
                "Apache License, Version 2.0",
            ):
                if marker not in readme:
                    error(f"README licensing attribution missing: {marker}")
        for relative in ["pyproject.toml", *contracts]:
            if relative not in images:
                continue
            text = _licensing_text(images[relative])
            for token in CONFLICTING_PROJECT_LICENSES:
                if token in text:
                    error(f"conflicting project license token in {relative}: {token}")
        policy_name = "policies/release-artifact-policy.json"
        if not present[policy_name]:
            error("invalid release artifact policy: file is missing")
        else:
            policy = _licensing_object(images[policy_name])
            roots = set(
                _licensing_names(
                    policy.get("product_root_files"), "policy root files", 4096
                )
            )
            missing = sorted(REQUIRED_ROOT_FILES - roots)
            if missing:
                error(
                    f"publication files absent from release artifact policy: {missing}"
                )
        report = {
            **base,
            "valid": error_count == 0,
            "corpus_complete": True,
            "checked_file_count": len(images),
            "files": [
                {
                    "path": relative,
                    "sha256": hashlib.sha256(images[relative]).hexdigest(),
                }
                for relative in sorted(images, key=Path)
            ],
            "errors": errors,
            "error_count": error_count,
            "errors_truncated": error_count > len(errors),
        }
        bounded_json_value(report)
        return report
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return {
            **base,
            "valid": False,
            "corpus_complete": False,
            "checked_file_count": None,
            "files": [],
            "errors": ["licensing inputs are invalid or unavailable"],
            "error_count": None,
            "errors_truncated": False,
        }


def _licensing_report_target(root: Path, destination: Path | None) -> Path:
    from .archive_io import reject_path_links
    from .input_files import relative_source_path
    from .numeric_inputs import bounded_text

    target = root / "evidence/licensing-consistency-report.json"
    if destination is not None:
        if type(destination) is not type(Path()):
            raise ValueError("report destination must be an actual filesystem path")
        bounded_text(str(destination), "report destination", maximum=4096, strip=False)
        if ".." in destination.parts:
            raise ValueError("report destination contains parent traversal")
        target = destination if destination.is_absolute() else root / destination
    bounded_text(str(target), "report destination", maximum=4096, strip=False)
    relative_source_path(target.relative_to(root).as_posix())
    reject_path_links(target)
    resolved = target.resolve(strict=False)
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("report destination escapes its root")
    if target.exists() and not target.is_file():
        raise ValueError("report destination must be a regular file")
    return target


def write_licensing_report(
    root: Path, destination: Path | None = None
) -> dict[str, Any]:
    from .input_files import directory_root
    from .numeric_inputs import bounded_json_value

    root = directory_root(root)
    target = _licensing_report_target(root, destination)
    report = validate_licensing(root)
    bounded_json_value(report)
    payload = (
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_LICENSING_REPORT_BYTES:
        raise ValueError("licensing report byte budget exhausted before publication")
    if _licensing_report_target(root, destination) != target:
        raise ValueError("report destination changed during evaluation")
    target.parent.mkdir(parents=True, exist_ok=True)
    if _licensing_report_target(root, destination) != target:
        raise ValueError("report destination changed before writing")
    target.write_bytes(payload)
    return {**report, "report": target.relative_to(root).as_posix()}
