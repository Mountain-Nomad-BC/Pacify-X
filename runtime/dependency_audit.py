"""Validate packaged Python dependency closure against project declarations."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import tomllib
from typing import Any

from .archive_io import (
    member_identity,
    portable_member_name,
    read_stream_bytes,
    reject_path_links,
)
from .json_io import bounded_strings, decode_json_object


def _control_images(root: Path) -> dict[str, bytearray]:
    if not isinstance(root, Path):
        raise ValueError("dependency audit root must be a Path")
    reject_path_links(root)
    root = root.resolve(strict=True)
    controls = {
        "registry/python_dependency_ownership.json": 4 * 1024 * 1024,
        "pyproject.toml": 1024 * 1024,
        "requirements-release.txt": 4 * 1024 * 1024,
        "policies/platform-support.json": 1024 * 1024,
        ".github/workflows/ci.yml": 512 * 1024,
        ".github/workflows/scheduled-assurance.yml": 512 * 1024,
        ".github/workflows/release.yml": 512 * 1024,
    }
    planned = []
    for name, ceiling in controls.items():
        path = root / name
        reject_path_links(path)
        if not path.is_file():
            raise ValueError("dependency control must be a regular file: " + name)
        size = path.stat().st_size
        if size > ceiling:
            raise ValueError("dependency control byte budget exceeded: " + name)
        planned.append((name, path, size, ceiling))
    remaining = 16 * 1024 * 1024
    if sum(size for _, _, size, _ in planned) > remaining:
        raise ValueError("dependency controls aggregate byte budget exceeded")
    images = {}
    for name, path, size, ceiling in planned:
        reject_path_links(path)
        with path.open("rb") as stream:
            image = read_stream_bytes(
                stream, max_bytes=min(ceiling, remaining), expected_size=size
            )
        remaining -= len(image)
        images[name] = image
    return images


def _validate_import_records(registry: dict[str, Any]) -> None:
    records = registry.get("records")
    if (
        registry.get("schema_version") != "1.0"
        or type(records) is not list
        or len(records) > 10_000
    ):
        raise ValueError("dependency inventory requires supported bounded records")
    classes = {
        "standard_library",
        "local_product",
        "required",
        "declared_required",
        "test_only",
        "unclassified",
    }
    modules = set()
    for record in records:
        if type(record) is not dict or set(record) != {
            "module",
            "distribution",
            "classification",
            "paths",
        }:
            raise ValueError("dependency inventory record is malformed")
        module, classification, distribution = (
            record["module"],
            record["classification"],
            record["distribution"],
        )
        if (
            type(module) is not str
            or len(module) > 256
            or not module.isidentifier()
            or module in modules
        ):
            raise ValueError("dependency module identity must be bounded and unique")
        modules.add(module)
        if type(classification) is not str or classification not in classes:
            raise ValueError("unknown dependency classification")
        if classification in {"required", "declared_required", "test_only"}:
            if (
                type(distribution) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", distribution)
                is None
            ):
                raise ValueError(
                    "classified dependency distribution must be bounded text"
                )
        elif distribution is not None:
            raise ValueError(
                "local, standard-library and unclassified imports cannot assert a distribution"
            )
        paths = record["paths"]
        if type(paths) is not list or not 1 <= len(paths) <= 10_000:
            raise ValueError("dependency source paths require a bounded nonempty list")
        seen = set()
        for path in bounded_strings(
            paths, max_items=10_000, max_item_bytes=4096, max_bytes=4 * 1024 * 1024
        ):
            portable_member_name(path, allow_directory=False)
            identity = member_identity(path)
            if identity in seen or not path.endswith(".py"):
                raise ValueError(
                    "dependency source paths must be unique portable Python paths"
                )
            seen.add(identity)
        if len(seen) != len(paths):
            raise ValueError("duplicate dependency source path")


def _dependency_names(values: object) -> set[str]:
    if type(values) is not list:
        raise ValueError("dependency declarations require a string array")
    return {
        item.split("=", 1)[0].casefold()
        for item in bounded_strings(
            values, max_items=1024, max_item_bytes=4096, max_bytes=1024 * 1024
        )
    }


def _lock_hash_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line and not line.startswith("--hash"):
            current = line.split("==", 1)[0].casefold()
            counts.setdefault(current, 0)
        if current is not None:
            counts[current] += line.count("--hash=sha256:")
    return counts


def validate_dependency_closure(root: Path) -> dict[str, Any]:
    try:
        return _validate_dependency_closure(_control_images(root))
    except (OSError, KeyError, TypeError, ValueError, RecursionError) as error:
        return {
            "schema_version": "1.0",
            "valid": False,
            "module_count": 0,
            "unclassified": 0,
            "runtime_dependency_count": 0,
            "release_dependency_count": 0,
            "build_requirements": [],
            "lock_sha256": None,
            "lock_hash_counts": {},
            "errors": [str(error)],
        }


def _validate_dependency_closure(images: dict[str, bytearray]) -> dict[str, Any]:
    registry = decode_json_object(
        images["registry/python_dependency_ownership.json"], max_bytes=4 * 1024 * 1024
    )
    _validate_import_records(registry)
    config = tomllib.loads(images["pyproject.toml"].decode("utf-8"))
    project = config["project"]
    build_system = config.get("build-system", {})
    if type(project) is not dict or type(build_system) is not dict:
        raise ValueError("project and build-system controls must be tables")
    runtime_dependencies = _dependency_names(project.get("dependencies", []))
    optional_values = project.get("optional-dependencies", {})
    if type(optional_values) is not dict or len(optional_values) > 64:
        raise ValueError("optional dependency groups require a bounded object")
    optional = {
        group: _dependency_names(values) for group, values in optional_values.items()
    }
    errors: list[str] = []
    for record in registry["records"]:
        classification = record["classification"]
        distribution = str(record.get("distribution") or "").casefold()
        if classification == "unclassified":
            errors.append(f"unclassified packaged import: {record['module']}")
        elif (
            classification in {"required", "declared_required"}
            and distribution not in runtime_dependencies
        ):
            errors.append(f"undeclared runtime distribution: {record['distribution']}")
        elif (
            classification == "test_only"
            and distribution not in optional.get("test", set())
            and distribution not in optional.get("release", set())
        ):
            errors.append(f"undeclared test distribution: {record['distribution']}")
    lock_bytes = images["requirements-release.txt"]
    lock_text = lock_bytes.decode("utf-8")
    lock = {
        line.split("==", 1)[0].casefold(): line.split("==", 1)[1]
        for line in lock_text.splitlines()
        if line and not line.startswith("#") and "==" in line
    }
    lock_hash_counts = _lock_hash_counts(lock_text)
    required_release = optional.get("release", set())
    if required_release != set(lock):
        errors.append(
            f"release lock mismatch: missing={sorted(required_release - set(lock))} extra={sorted(set(lock) - required_release)}"
        )
    unhashed = sorted(name for name in lock if lock_hash_counts.get(name, 0) < 1)
    if unhashed:
        errors.append(f"release lock entries without hashes: {unhashed}")
    platform_policy = decode_json_object(
        images["policies/platform-support.json"], max_bytes=1024 * 1024
    )
    matrix_size = len(platform_policy.get("python_minors", ())) * len(
        platform_policy.get("ci_runners", {})
    )
    for distribution in ("coverage", "pyyaml"):
        if lock_hash_counts.get(distribution, 0) < matrix_size:
            errors.append(
                f"{distribution} hash allowlist does not cover the supported Python/OS matrix"
            )
    if lock_hash_counts.get("ruff", 0) < len(platform_policy.get("ci_runners", {})):
        errors.append("ruff hash allowlist does not cover the supported OS matrix")
    build_requirements = set(build_system.get("requires", ()))
    if build_requirements != {"setuptools==84.0.0"}:
        errors.append("build-system backend must be exact-pinned to setuptools==84.0.0")
    lock_install = "python -m pip install --require-hashes -r requirements-release.txt"
    for relative in (
        ".github/workflows/ci.yml",
        ".github/workflows/scheduled-assurance.yml",
    ):
        if lock_install not in images[relative].decode("utf-8"):
            errors.append(f"{relative} does not install the authoritative hash lock")
    release_workflow = images[".github/workflows/release.yml"].decode("utf-8")
    forbidden_release_builders = (
        "release finalize",
        "pip download",
        "PACIFY_X_RELEASE_SIGNING_KEY",
        "npm run package",
    )
    for forbidden in forbidden_release_builders:
        if forbidden in release_workflow:
            errors.append(
                ".github/workflows/release.yml post-certification transport contains "
                f"a forbidden builder or signing authority: {forbidden}"
            )
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "module_count": len(registry["records"]),
        "unclassified": sum(
            item["classification"] == "unclassified" for item in registry["records"]
        ),
        "runtime_dependency_count": len(runtime_dependencies),
        "release_dependency_count": len(required_release),
        "build_requirements": sorted(build_requirements),
        "lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "lock_hash_counts": lock_hash_counts,
        "errors": errors,
    }
