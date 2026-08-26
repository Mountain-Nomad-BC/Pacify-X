"""Hash-locked, scrubbed, offline release-toolchain controls."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import locale
import os
from pathlib import Path
import platform
import re
import sys
import tomllib
from typing import Any, Mapping


LOCK_LINE = re.compile(
    r"^([A-Za-z0-9_.-]+)==([^\s]+)(?:\s+--hash=sha256:([0-9a-f]{64}))+$"
)
HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")
ENVIRONMENT_ALLOWLIST = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "TZ",
    "PYTHONUTF8",
    # Windows OpenSSH loads system crypto configuration beneath PROGRAMDATA.
    # Without it ssh-keygen exits 255 without diagnostics, which prevents the
    # release suite from exercising signed-grant and signed-certificate paths.
    # This is machine configuration, not a user/profile identity variable.
    "PROGRAMDATA",
}


def parse_release_lock(path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    logical_lines: list[tuple[int, str]] = []
    pending = ""
    pending_line = 0
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        stripped = line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        if pending and (not stripped or stripped.startswith("#")):
            errors.append(
                f"line {line_number}: blank or comment interrupts a continued requirement"
            )
            pending = ""
            continue
        if not pending:
            pending_line = line_number
        pending = f"{pending} {stripped}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical_lines.append((pending_line, pending))
        pending = ""
    if pending:
        errors.append(f"line {pending_line}: unterminated continued requirement")

    for line_number, logical_line in logical_lines:
        match = LOCK_LINE.fullmatch(logical_line)
        if not match:
            errors.append(
                f"line {line_number}: release requirement must be exact-pinned and hash-locked"
            )
            continue
        name, version = match.group(1), match.group(2)
        normalized = name.casefold().replace("_", "-")
        hashes = sorted(set(HASH.findall(logical_line)))
        if normalized in seen:
            errors.append(f"line {line_number}: duplicate release requirement {name}")
        seen.add(normalized)
        if not hashes:
            errors.append(f"line {line_number}: release requirement has no sha256 hash")
        records.append(
            {
                "name": name,
                "normalized_name": normalized,
                "version": version,
                "sha256": hashes,
            }
        )
    return {
        "valid": bool(records) and not errors,
        "records": records,
        "required_count": len(records),
        "errors": errors,
    }


def scrub_release_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    inherited = source or os.environ
    clean = {
        key: value
        for key, value in inherited.items()
        if key.upper() in ENVIRONMENT_ALLOWLIST
    }
    clean.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": "0",
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "NO_COLOR": "1",
        }
    )
    return clean


def build_wheelhouse_manifest(wheelhouse: Path, lock_path: Path) -> dict[str, Any]:
    root = wheelhouse.resolve(strict=True)
    lock = parse_release_lock(lock_path)
    allowed_hashes = {digest for item in lock["records"] for digest in item["sha256"]}
    records: list[dict[str, Any]] = []
    errors = list(lock["errors"])
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.casefold() != ".whl":
            errors.append(f"wheelhouse contains a non-wheel artifact: {path.name}")
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        records.append(
            {"filename": path.name, "size_bytes": len(data), "sha256": digest}
        )
        if digest not in allowed_hashes:
            errors.append(
                f"wheelhouse artifact is not admitted by the release lock: {path.name}"
            )
    observed = {record["sha256"] for record in records}
    for item in lock["records"]:
        if not observed.intersection(item["sha256"]):
            errors.append(
                f"wheelhouse is missing locked artifact for {item['name']}=={item['version']}"
            )
    payload = {
        "schema_version": "1.0",
        "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "artifacts": records,
    }
    return {
        **payload,
        "manifest_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "valid": not errors,
        "errors": errors,
    }


def offline_install_command(
    python_executable: str, lock_path: Path, wheelhouse: Path
) -> list[str]:
    return [
        python_executable,
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "--require-hashes",
        "-r",
        str(lock_path),
    ]


def toolchain_identity(python_executable: str | None = None) -> dict[str, Any]:
    executable = Path(python_executable or sys.executable).resolve(strict=True)
    return {
        "python_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "operating_system": platform.system(),
        "architecture": platform.machine(),
        "locale": locale.getlocale(),
        "timezone": os.environ.get("TZ", "system-default"),
        "filesystem_case_sensitive": os.path.normcase("A") != os.path.normcase("a"),
    }


def support_matrix(root: Path) -> dict[str, Any]:
    path = root.resolve() / "policies" / "platform-support.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "python_requires",
        "python_minors",
        "operating_systems",
        "ci_runners",
        "platform_checks",
    }
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"platform support policy is incomplete: {', '.join(missing)}")
    return value


def validate_support_matrix(root: Path) -> dict[str, Any]:
    root = root.resolve()
    policy = support_matrix(root)
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = config["project"]
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    errors: list[str] = []
    if project.get("requires-python") != policy["python_requires"]:
        errors.append("project requires-python does not match the support policy")
    classifiers = set(project.get("classifiers", ()))
    published_python = {
        classifier.rsplit("::", 1)[-1].strip()
        for classifier in classifiers
        if classifier.startswith("Programming Language :: Python :: 3.")
    }
    published_platforms = {
        "Windows"
        if classifier == "Operating System :: Microsoft :: Windows"
        else "Linux"
        if classifier == "Operating System :: POSIX :: Linux"
        else "Darwin"
        if classifier == "Operating System :: MacOS"
        else ""
        for classifier in classifiers
    } - {""}
    if published_python != set(policy["python_minors"]):
        errors.append("published Python classifiers do not match the support policy")
    if published_platforms != set(policy["operating_systems"]):
        errors.append("published platform classifiers do not match the support policy")
    missing_versions = [
        version for version in policy["python_minors"] if f'"{version}"' not in workflow
    ]
    missing_runners = [
        runner for runner in policy["ci_runners"].values() if runner not in workflow
    ]
    errors.extend(
        f"CI matrix is missing Python {version}" for version in missing_versions
    )
    errors.extend(f"CI matrix is missing runner {runner}" for runner in missing_runners)
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "python_requires": policy["python_requires"],
        "python_minors": list(policy["python_minors"]),
        "operating_systems": list(policy["operating_systems"]),
        "ci_runners": dict(policy["ci_runners"]),
        "errors": errors,
    }


def certification_platform_binding(
    identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    toolchain = dict(identity or toolchain_identity())
    version = str(toolchain.get("python_version", ""))
    components = version.split(".")
    return {
        "python_version": version,
        "python_minor": ".".join(components[:2]) if len(components) >= 2 else "",
        "python_implementation": str(toolchain.get("python_implementation", "")),
        "operating_system": str(toolchain.get("operating_system", "")),
        "platform": str(toolchain.get("platform", "")),
        "architecture": str(toolchain.get("architecture", "")),
    }


def validate_certification_platform(
    root: Path, binding: Mapping[str, Any]
) -> dict[str, Any]:
    policy = support_matrix(root)
    required = {
        "python_version",
        "python_minor",
        "python_implementation",
        "operating_system",
        "platform",
        "architecture",
    }
    errors = [
        f"release certificate platform is missing {key}"
        for key in sorted(required)
        if not binding.get(key)
    ]
    if binding.get("python_minor") not in policy["python_minors"]:
        errors.append(
            "release certificate Python minor is outside the supported matrix"
        )
    if binding.get("operating_system") not in policy["operating_systems"]:
        errors.append(
            "release certificate operating system is outside the supported matrix"
        )
    return {"valid": not errors, "errors": errors}


def validate_release_lock(root: Path) -> dict[str, Any]:
    lock_path = root.resolve() / "requirements-release.txt"
    result = parse_release_lock(lock_path)
    return {**result, "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest()}


def validate_release_environment(root: Path) -> dict[str, Any]:
    root = root.resolve()
    lock_path = root / "requirements-release.txt"
    lock = parse_release_lock(lock_path)
    installed: dict[str, str | None] = {}
    errors = list(lock["errors"])
    for record in lock["records"]:
        name, expected = record["name"], record["version"]
        try:
            actual = importlib.metadata.version(name)
            installed[record["normalized_name"]] = actual
            if actual != expected:
                errors.append(f"{name}: installed {actual}, required {expected}")
        except importlib.metadata.PackageNotFoundError:
            installed[record["normalized_name"]] = None
            errors.append(f"{name}: missing from isolated release environment")
    matrix = validate_support_matrix(root)
    errors.extend(matrix["errors"])
    current_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    if current_minor not in matrix["python_minors"]:
        errors.append(f"release Python {current_minor} is outside the supported matrix")
    return {
        "schema_version": "2.0",
        "valid": not errors,
        "lock_valid": lock["valid"],
        "python": platform.python_version(),
        "platform": platform.platform(),
        "required_count": len(lock["records"]),
        "installed": installed,
        "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "toolchain": toolchain_identity(),
        "errors": errors,
    }
