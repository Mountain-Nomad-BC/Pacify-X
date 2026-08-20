"""Hermetic, read-only readiness classification for extension certification.

This module deliberately does not install dependencies or launch a browser/IDE.
It proves that the prerequisites needed by the later exact-artifact lanes are
present and compatible, or returns ``environment-unready`` with exact reasons.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Any, Iterable, Mapping, Sequence

from .release_environment import scrub_release_environment


SCHEMA_VERSION = "px.certification-readiness/1.0"
PROBE_TIMEOUT_SECONDS = 8.0
ENGINE_PROBE_TIMEOUT_SECONDS = 60.0
VERSION = re.compile(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?")
COMPARATOR = re.compile(r"^(>=|<=|>|<|=|==|\^|~)?\s*(\d+(?:\.\d+){0,2})$")


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = VERSION.search(value)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _satisfies_clause(version: tuple[int, int, int], clause: str) -> bool:
    match = COMPARATOR.fullmatch(clause.strip())
    if not match:
        raise ValueError(f"unsupported version constraint: {clause}")
    operator, raw_expected = match.groups()
    expected = _version_tuple(raw_expected)
    if expected is None:  # guarded by COMPARATOR; retained as a fail-closed check
        raise ValueError(f"invalid version constraint: {clause}")
    if operator == ">=":
        return version >= expected
    if operator == "<=":
        return version <= expected
    if operator == ">":
        return version > expected
    if operator == "<":
        return version < expected
    if operator == "^":
        ceiling = (expected[0] + 1, 0, 0)
        return expected <= version < ceiling
    if operator == "~":
        ceiling = (expected[0], expected[1] + 1, 0)
        return expected <= version < ceiling
    return version == expected


def version_satisfies(version: str, requirement: str | None) -> bool:
    """Evaluate the bounded semver subset used by the PX lock and manifests."""

    if not requirement:
        return True
    parsed = _version_tuple(version)
    if parsed is None:
        return False
    normalized = re.sub(r"(>=|<=|==|>|<|=|\^|~)\s+(?=\d)", r"\1", requirement)
    alternatives = [item.strip() for item in normalized.split("||") if item.strip()]
    if not alternatives:
        raise ValueError("version requirement is empty")
    for alternative in alternatives:
        clauses = [item for item in re.split(r"\s+", alternative) if item]
        if all(_satisfies_clause(parsed, clause) for clause in clauses):
            return True
    return False


def _resolve_executable(
    requested: str | None,
    names: Sequence[str],
    absolute_candidates: Iterable[Path] = (),
) -> Path | None:
    if requested:
        candidate = Path(requested).expanduser()
        if candidate.is_absolute() or candidate.parent != Path("."):
            return candidate.resolve() if candidate.is_file() else None
        resolved = shutil.which(requested)
        return Path(resolved).resolve() if resolved else None
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved).resolve()
    for candidate in absolute_candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _batch_command(executable: Path, arguments: Sequence[str]) -> list[str]:
    if platform.system() != "Windows" or executable.suffix.casefold() not in {
        ".cmd",
        ".bat",
    }:
        return [str(executable), *arguments]
    command_processor = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
    if not command_processor:
        raise OSError("Windows command processor is unavailable")
    return [command_processor, "/d", "/c", str(executable), *arguments]


def _run_probe(
    executable: Path,
    arguments: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            _batch_command(executable, arguments),
            cwd=cwd,
            env=scrub_release_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "ok": False,
            "exit_code": None,
            "output": "",
            "diagnostic": f"{type(error).__name__}: {error}",
        }
    output = "\n".join(
        item.strip() for item in (completed.stdout, completed.stderr) if item.strip()
    )[:4096]
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "output": output,
        "diagnostic": "" if completed.returncode == 0 else output or "probe failed",
    }


def _tool_result(
    identifier: str,
    executable: Path | None,
    requirement: str | None,
    *,
    cwd: Path,
    arguments: Sequence[str] = ("--version",),
    timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": identifier,
        "required": True,
        "status": "missing",
        "executable": str(executable) if executable else None,
        "version": None,
        "requirement": requirement,
        "diagnostic": "required executable was not found",
    }
    if executable is None:
        return base
    probe = _run_probe(
        executable, arguments, cwd=cwd, timeout_seconds=timeout_seconds
    )
    if not probe["ok"]:
        return {
            **base,
            "status": "probe-failed",
            "diagnostic": probe["diagnostic"],
        }
    version_match = VERSION.search(probe["output"])
    version = version_match.group(0) if version_match else None
    if version is None:
        return {
            **base,
            "status": "probe-failed",
            "diagnostic": "version probe returned no parseable version",
        }
    try:
        compatible = version_satisfies(version, requirement)
    except ValueError as error:
        return {
            **base,
            "version": version,
            "status": "invalid-configuration",
            "diagnostic": str(error),
        }
    return {
        **base,
        "version": version,
        "status": "ready" if compatible else "incompatible",
        "diagnostic": "" if compatible else f"found {version}; requires {requirement}",
    }


def _windows_file_version(executable: Path) -> str | None:
    if platform.system() != "Windows":
        return None
    try:
        import ctypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(executable), None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(
            str(executable), 0, size, buffer
        ):
            return None
        pointer = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not ctypes.windll.version.VerQueryValueW(
            buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)
        ):
            return None

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [
                ("signature", ctypes.c_uint32),
                ("structure_version", ctypes.c_uint32),
                ("file_version_ms", ctypes.c_uint32),
                ("file_version_ls", ctypes.c_uint32),
            ]

        value = ctypes.cast(pointer, ctypes.POINTER(FixedFileInfo)).contents
        return ".".join(
            map(
                str,
                (
                    value.file_version_ms >> 16,
                    value.file_version_ms & 0xFFFF,
                    value.file_version_ls >> 16,
                    value.file_version_ls & 0xFFFF,
                ),
            )
        )
    except (AttributeError, OSError, ValueError):
        return None


def _browser_result(executable: Path | None, *, cwd: Path) -> dict[str, Any]:
    if executable is not None:
        version = _windows_file_version(executable)
        if version:
            return {
                "id": "browser",
                "required": True,
                "status": "ready",
                "executable": str(executable),
                "version": version,
                "requirement": None,
                "diagnostic": "",
            }
    return _tool_result("browser", executable, None, cwd=cwd)


def _python_requirement(engine_root: Path) -> tuple[str | None, str | None]:
    try:
        document = tomllib.loads(
            (engine_root / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError) as error:
        return None, f"cannot read engine pyproject.toml: {error}"
    requirement = document.get("project", {}).get("requires-python")
    if not isinstance(requirement, str) or not requirement.strip():
        return None, "engine pyproject.toml does not declare requires-python"
    return requirement.replace(",", " "), None


def _build_requirement(engine_root: Path) -> tuple[str | None, str | None]:
    try:
        document = tomllib.loads(
            (engine_root / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError) as error:
        return None, f"cannot read engine pyproject.toml: {error}"
    groups = document.get("project", {}).get("optional-dependencies", {})
    requirements = [
        str(item)
        for group in ("build", "release")
        for item in groups.get(group, ())
        if str(item).casefold().startswith("build==")
    ]
    if not requirements:
        return None, "engine does not exact-pin the Python build package"
    versions = sorted({item.split("==", 1)[1] for item in requirements})
    if len(versions) != 1:
        return None, "engine declares conflicting Python build package versions"
    return f"=={versions[0]}", None


def _python_build_result(
    python_executable: Path | None,
    requirement: str | None,
    configuration_error: str | None,
    *,
    cwd: Path,
) -> dict[str, Any]:
    base = {
        "id": "python-build",
        "required": True,
        "status": "missing",
        "executable": str(python_executable) if python_executable else None,
        "version": None,
        "requirement": requirement,
        "diagnostic": configuration_error or "Python executable is unavailable",
    }
    if configuration_error:
        return {**base, "status": "invalid-configuration"}
    if python_executable is None:
        return base
    probe = _run_probe(
        python_executable,
        (
            "-c",
            "import importlib.metadata as m; print(m.version('build'))",
        ),
        cwd=cwd,
    )
    if not probe["ok"]:
        return {
            **base,
            "diagnostic": "Python build package is missing or cannot be queried",
        }
    version_match = VERSION.search(probe["output"])
    version = version_match.group(0) if version_match else None
    compatible = bool(version and version_satisfies(version, requirement))
    return {
        **base,
        "version": version,
        "status": "ready" if compatible else "incompatible",
        "diagnostic": "" if compatible else f"found {version}; requires {requirement}",
    }


def _read_extension_contract(
    extension_root: Path | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    if extension_root is None:
        return None, None, ["extension root was not supplied"]
    errors: list[str] = []
    package: dict[str, Any] | None = None
    lock: dict[str, Any] | None = None
    documents = (("package.json", "package"), ("package-lock.json", "lock"))
    for filename, destination in documents:
        path = extension_root / filename
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("document must be a JSON object")
            if destination == "package":
                package = value
            else:
                lock = value
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"{filename}: {error}")
    return package, lock, errors


def _node_requirements(
    lock: Mapping[str, Any] | None,
) -> tuple[list[str], str | None]:
    if lock is None:
        return [], "package-lock.json is unavailable"
    packages = lock.get("packages")
    if not isinstance(packages, Mapping):
        return [], "package-lock.json does not contain a packages map"
    requirements = sorted(
        {
            str(engines["node"]).strip()
            for value in packages.values()
            if isinstance(value, Mapping)
            and isinstance((engines := value.get("engines")), Mapping)
            and engines.get("node")
        }
    )
    if not requirements:
        return [], "locked packages do not declare a Node requirement"
    return requirements, None


def _node_result(
    executable: Path | None,
    requirements: Sequence[str],
    configuration_error: str | None,
    *,
    cwd: Path,
) -> dict[str, Any]:
    rendered = " AND ".join(f"({item})" for item in requirements) or None
    base: dict[str, Any] = {
        "id": "node",
        "required": True,
        "status": "missing",
        "executable": str(executable) if executable else None,
        "version": None,
        "requirement": rendered,
        "diagnostic": configuration_error or "required executable was not found",
    }
    if configuration_error:
        return {**base, "status": "invalid-configuration"}
    if executable is None:
        return base
    probe = _run_probe(executable, ("--version",), cwd=cwd)
    if not probe["ok"]:
        return {**base, "status": "probe-failed", "diagnostic": probe["diagnostic"]}
    version_match = VERSION.search(probe["output"])
    version = version_match.group(0) if version_match else None
    if version is None:
        return {**base, "status": "probe-failed", "diagnostic": "version probe returned no parseable version"}
    try:
        incompatible = [
            requirement
            for requirement in requirements
            if not version_satisfies(version, requirement)
        ]
    except ValueError as error:
        return {**base, "version": version, "status": "invalid-configuration", "diagnostic": str(error)}
    return {
        **base,
        "version": version,
        "status": "ready" if not incompatible else "incompatible",
        "diagnostic": "" if not incompatible else f"found {version}; incompatible with: {', '.join(incompatible)}",
    }


def _lock_result(
    package: Mapping[str, Any] | None,
    lock: Mapping[str, Any] | None,
    read_errors: Sequence[str],
    extension_root: Path | None,
) -> dict[str, Any]:
    errors = list(read_errors)
    if package is not None and lock is not None:
        if lock.get("lockfileVersion") != 3:
            errors.append("package-lock.json must use lockfileVersion 3")
        packages = lock.get("packages")
        root = packages.get("") if isinstance(packages, Mapping) else None
        if not isinstance(root, Mapping):
            errors.append("package-lock.json is missing the root package record")
        else:
            for field in ("name", "version", "dependencies", "devDependencies"):
                if package.get(field, {}) != root.get(field, {}):
                    errors.append(
                        f"package-lock root {field} differs from package.json"
                    )
        for group in ("dependencies", "devDependencies"):
            declared = package.get(group, {})
            if not isinstance(declared, Mapping):
                errors.append(f"package.json {group} must be an object")
                continue
            floating = [
                name
                for name, value in declared.items()
                if not re.fullmatch(
                    r"\d+(?:\.\d+){2}(?:[-+][A-Za-z0-9.-]+)?", str(value)
                )
            ]
            if floating:
                errors.append(
                    f"package.json {group} is not exact-pinned: "
                    f"{', '.join(sorted(floating))}"
                )
            if extension_root is not None:
                for name, expected in sorted(declared.items()):
                    installed_path = (
                        extension_root / "node_modules" / name / "package.json"
                    )
                    try:
                        installed = json.loads(
                            installed_path.read_text(encoding="utf-8")
                        )
                        actual = installed.get("version")
                    except (OSError, json.JSONDecodeError, AttributeError) as error:
                        errors.append(
                            f"installed dependency {name} is unavailable: {error}"
                        )
                        continue
                    if actual != expected:
                        errors.append(
                            f"installed dependency {name} is {actual}; "
                            f"expected {expected}"
                        )
    return {
        "id": "node-package-lock",
        "required": True,
        "status": "ready" if not errors else "invalid-configuration",
        "executable": None,
        "version": str(lock.get("lockfileVersion")) if lock else None,
        "requirement": (
            "lockfileVersion 3; exact direct pins; installed direct dependency parity"
        ),
        "diagnostic": "; ".join(errors),
    }


def _engine_result(
    engine_root: Path,
    python_executable: Path | None,
) -> dict[str, Any]:
    required_paths = (
        "pyproject.toml",
        "runtime/cli.py",
        "registry/capability_map.json",
    )
    missing = [item for item in required_paths if not (engine_root / item).is_file()]
    base = {
        "id": "engine",
        "required": True,
        "status": "invalid-configuration",
        "executable": str(python_executable) if python_executable else None,
        "version": None,
        "requirement": "PX root plus successful runtime.cli validate",
        "diagnostic": "",
    }
    if missing:
        return {**base, "diagnostic": f"engine root is missing: {', '.join(missing)}"}
    if python_executable is None:
        return {**base, "status": "missing", "diagnostic": "Python is unavailable"}
    probe = _run_probe(
        python_executable,
        ("-m", "runtime.cli", "--root", str(engine_root), "validate"),
        cwd=engine_root,
        timeout_seconds=ENGINE_PROBE_TIMEOUT_SECONDS,
    )
    if not probe["ok"]:
        return {
            **base,
            "status": "probe-failed",
            "diagnostic": probe["diagnostic"] or "engine validation failed",
        }
    try:
        payload = json.loads(probe["output"])
    except json.JSONDecodeError as error:
        return {
            **base,
            "status": "probe-failed",
            "diagnostic": f"engine validation emitted invalid JSON: {error}",
        }
    if payload.get("valid") is not True:
        return {
            **base,
            "status": "incompatible",
            "diagnostic": "engine validation did not report valid=true",
        }
    try:
        version = tomllib.loads(
            (engine_root / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        version = None
    return {**base, "status": "ready", "version": version, "diagnostic": ""}


def _browser_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    if platform.system() == "Windows":
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.extend(
                    (
                        Path(root) / "Microsoft/Edge/Application/msedge.exe",
                        Path(root) / "Google/Chrome/Application/chrome.exe",
                    )
                )
    elif platform.system() == "Darwin":
        candidates.extend(
            (
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            )
        )
    return tuple(candidates)


def _vscode_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    if platform.system() == "Windows":
        local = os.environ.get("LOCALAPPDATA")
        program_files = os.environ.get("PROGRAMFILES")
        if local:
            candidates.append(Path(local) / "Programs/Microsoft VS Code/bin/code.cmd")
        if program_files:
            candidates.append(Path(program_files) / "Microsoft VS Code/bin/code.cmd")
    elif platform.system() == "Darwin":
        candidates.append(
            Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
        )
    return tuple(candidates)


def assess_certification_readiness(
    engine_root: Path,
    extension_root: Path | None,
    *,
    python: str | None = None,
    node: str | None = None,
    npm: str | None = None,
    browser: str | None = None,
    vscode: str | None = None,
) -> dict[str, Any]:
    """Classify every required certification prerequisite without mutation."""

    engine_root = engine_root.expanduser().resolve()
    extension_root = extension_root.expanduser().resolve() if extension_root else None
    package, lock, extension_errors = _read_extension_contract(extension_root)
    python_requirement, python_config_error = _python_requirement(engine_root)
    build_requirement, build_config_error = _build_requirement(engine_root)
    node_requirements, node_config_error = _node_requirements(lock)

    python_executable = (
        _resolve_executable(python, ("python", "python3"))
        if python
        else Path(sys.executable).resolve()
    )
    node_executable = _resolve_executable(node, ("node",))
    npm_executable = _resolve_executable(npm, ("npm",))
    browser_executable = _resolve_executable(
        browser,
        ("msedge", "google-chrome", "chromium", "chromium-browser"),
        _browser_candidates(),
    )
    vscode_executable = _resolve_executable(
        vscode, ("code", "code-insiders"), _vscode_candidates()
    )
    cwd = engine_root if engine_root.is_dir() else Path.cwd()

    python_result = _tool_result(
        "python", python_executable, python_requirement, cwd=cwd
    )
    if python_config_error:
        python_result.update(
            status="invalid-configuration", diagnostic=python_config_error
        )
    node_result = _node_result(
        node_executable, node_requirements, node_config_error, cwd=cwd
    )

    vscode_requirement = None
    if package is not None:
        engines = package.get("engines")
        if isinstance(engines, Mapping) and engines.get("vscode"):
            vscode_requirement = str(engines["vscode"])
    prerequisites = [
        python_result,
        _python_build_result(
            python_executable, build_requirement, build_config_error, cwd=cwd
        ),
        node_result,
        _tool_result("npm", npm_executable, None, cwd=cwd),
        _lock_result(package, lock, extension_errors, extension_root),
        _browser_result(browser_executable, cwd=cwd),
        _tool_result(
            "vscode",
            vscode_executable,
            vscode_requirement,
            cwd=cwd,
            timeout_seconds=30.0,
        ),
        _engine_result(engine_root, python_executable),
    ]
    unready = [item for item in prerequisites if item["status"] != "ready"]
    errors = [f"{item['id']}: {item['diagnostic']}" for item in unready]
    return {
        "schema_version": SCHEMA_VERSION,
        "classification": "environment-unready" if unready else "ready",
        "valid": not unready,
        "engine_root": str(engine_root),
        "extension_root": str(extension_root) if extension_root else None,
        "platform": {
            "operating_system": platform.system(),
            "architecture": platform.machine(),
        },
        "probe_policy": {
            "read_only": True,
            "network_access": "not-used",
            "install_performed": False,
            "environment": "allowlisted-and-scrubbed",
            "timeout_seconds": ENGINE_PROBE_TIMEOUT_SECONDS,
            "parameterized_roots": True,
        },
        "prerequisites": prerequisites,
        "summary": {
            "required": len(prerequisites),
            "ready": len(prerequisites) - len(unready),
            "unready": len(unready),
        },
        "errors": errors,
    }


__all__ = ["SCHEMA_VERSION", "assess_certification_readiness", "version_satisfies"]
