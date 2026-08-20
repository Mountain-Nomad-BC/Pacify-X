"""Build, inspect, install, and verify one immutable release artifact set."""

from __future__ import annotations

import hashlib
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import tarfile
import tomllib
from typing import Any, Callable, Mapping
import venv
import zipfile

from .release_environment import scrub_release_environment


Runner = Callable[..., subprocess.CompletedProcess[str]]
SKILL_EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
SKILL_EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _intermediate_records(paths: list[Path], root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for base in sorted(paths, key=lambda item: item.name.casefold()):
        if base.is_symlink():
            raise ValueError(f"build intermediate is a symbolic link: {base.name}")
        candidates = (
            [base]
            if base.is_file()
            else sorted(base.rglob("*"), key=lambda item: item.as_posix().casefold())
        )
        for path in candidates:
            if path.is_symlink():
                raise ValueError(
                    f"build intermediate contains a symbolic link: {path.relative_to(root).as_posix()}"
                )
            if path.is_file():
                records.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "size_bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                )
    return records


def quarantine_build_intermediates(root: Path, custody_root: Path) -> dict[str, Any]:
    """Move backend-created source-tree intermediates into external custody."""
    root = root.resolve(strict=True)
    custody_root = custody_root.resolve()
    candidates = [path for path in (root / "build", root / "dist") if path.exists()]
    candidates.extend(
        sorted(root.glob("*.egg-info"), key=lambda item: item.name.casefold())
    )
    errors: list[str] = []
    try:
        before = _intermediate_records(candidates, root)
    except (OSError, ValueError) as error:
        return {
            "valid": False,
            "moved": [],
            "records": [],
            "hard_delete": False,
            "errors": [str(error)],
        }
    moved: list[str] = []
    custody_root.mkdir(parents=True, exist_ok=True)
    for source in candidates:
        destination = custody_root / source.name
        if destination.exists():
            errors.append(f"build-intermediate custody collision: {source.name}")
            continue
        try:
            source.replace(destination)
            moved.append(source.name)
        except OSError as error:
            errors.append(
                f"could not quarantine build intermediate {source.name}: {error}"
            )
    remaining = [path.name for path in (root / "build", root / "dist") if path.exists()]
    remaining.extend(path.name for path in root.glob("*.egg-info"))
    errors.extend(
        f"build intermediate remains in product tree: {name}"
        for name in sorted(set(remaining))
    )
    receipt = {
        "schema_version": "1.0",
        "valid": not errors,
        "moved": moved,
        "records": before,
        "file_count": len(before),
        "hard_delete": False,
        "errors": errors,
    }
    (custody_root / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return receipt


def _distribution_name(name: str) -> str:
    return re_sub_non_alphanumeric(name).strip("_").lower()


def re_sub_non_alphanumeric(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


def _artifact_class(source_path: str) -> tuple[str, str]:
    top = source_path.split("/", 1)[0]
    if top == "runtime":
        return "runtime-module", "engineering-bootstrap-runtime"
    if top == "builders":
        return "builder-module", "engineering-bootstrap-builders"
    if top == "tests":
        return "release-testkit", "release-certification"
    if top == "scripts":
        return "release-build-control", "release-certification"
    if top == ".px":
        return (
            "skill-tool" if "/scripts/" in f"/{source_path}" else "skill-resource",
            "skill-orchestration",
        )
    return {
        "contracts": ("contract", "contract-runtime"),
        "policies": ("policy", "governance-runtime"),
        "registry": ("registry", "registry-runtime"),
        "orchestration": ("workflow", "workflow-runtime"),
        "templates": ("template", "commissioning-runtime"),
        "bootstrap": ("bootstrap-resource", "bootstrap-runtime"),
        "models": ("model-policy", "model-runtime"),
        "evidence": ("bundled-evidence", "evidence-runtime"),
        "docs": ("documentation", "release-documentation"),
    }.get(top, ("project-metadata", "release-engineering"))


def _record(
    root: Path, source: Path, installed_path: str, target: str
) -> dict[str, Any]:
    relative = source.relative_to(root).as_posix()
    artifact_class, owner = _artifact_class(relative)
    return {
        "source_path": relative,
        "installed_path": installed_path,
        "artifact_type": artifact_class,
        "owner": owner,
        "source_sha256": _sha256(source),
        "source_size_bytes": source.stat().st_size,
        "required": True,
        "package_target": target,
        "designation": "authoritative",
        "generated": False,
    }


def _manifest_sources(root: Path, manifest_path: Path) -> set[Path]:
    included: set[Path] = {root / "pyproject.toml", manifest_path}
    excluded: set[Path] = set()
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = shlex.split(line)
        if not parts:
            continue
        command, arguments = parts[0], parts[1:]
        if command == "include":
            for pattern in arguments:
                included.update(path for path in root.glob(pattern) if path.is_file())
        elif command == "exclude":
            for pattern in arguments:
                excluded.update(path for path in root.glob(pattern) if path.is_file())
        elif (
            command in {"recursive-include", "recursive-exclude"}
            and len(arguments) >= 2
        ):
            base = root / arguments[0]
            matches = (
                {
                    path
                    for pattern in arguments[1:]
                    for path in base.rglob(pattern)
                    if path.is_file()
                }
                if base.is_dir()
                else set()
            )
            (included if command == "recursive-include" else excluded).update(matches)
        else:
            raise ValueError(f"unsupported MANIFEST.in directive: {line}")
    return {
        path.resolve(strict=True)
        for path in included - excluded
        if path.is_file() and not path.is_symlink()
    }


def commissioned_skill_sources(root: Path) -> dict[str, dict[str, object]]:
    """Inventory every regular commissioned skill-owned source file."""
    records: dict[str, dict[str, object]] = {}
    skills = root / ".px/skills"
    for path in sorted(skills.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root)
        if (
            not path.is_file()
            or path.is_symlink()
            or SKILL_EXCLUDED_PARTS.intersection(relative.parts)
            or path.suffix.casefold() in SKILL_EXCLUDED_SUFFIXES
        ):
            continue
        key = relative.as_posix()
        records[key] = {
            "path": key,
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }
    return records


def verify_commissioned_skill_projection(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    source_only: set[str] | None = None,
) -> dict[str, Any]:
    """Prove exact source-to-wheel and source-to-sdist skill file coverage."""
    allowed_source_only = source_only or set()
    source = commissioned_skill_sources(root)
    projected: dict[str, dict[str, list[Mapping[str, Any]]]] = {
        "wheel": {},
        "sdist": {},
    }
    for record in manifest.get("records", ()):
        source_path = str(record.get("source_path", ""))
        target = str(record.get("package_target", ""))
        source_parts = Path(source_path).parts
        if (
            source_path.startswith(".px/skills/")
            and target in projected
            and "__pycache__" not in source_parts
            and Path(source_path).suffix.casefold() not in SKILL_EXCLUDED_SUFFIXES
        ):
            projected[target].setdefault(source_path, []).append(record)
    errors: list[str] = []
    for path, record in source.items():
        if path in allowed_source_only:
            if projected["wheel"].get(path):
                errors.append(f"source-only skill file appears in wheel: {path}")
            continue
        for target in ("wheel", "sdist"):
            matches = projected[target].get(path, [])
            if len(matches) != 1:
                errors.append(
                    f"skill projection count mismatch: {target}:{path}:{len(matches)}"
                )
                continue
            if matches[0].get("source_sha256") != record["sha256"]:
                errors.append(f"skill projection hash mismatch: {target}:{path}")
        wheel = projected["wheel"].get(path, [])
        if wheel and not str(wheel[0].get("installed_path", "")).endswith("/" + path):
            errors.append(f"skill wheel path is not equivalent: {path}")
    unknown_policy = allowed_source_only - set(source)
    errors.extend(
        f"source-only policy path does not exist: {path}"
        for path in sorted(unknown_policy)
    )
    payload = {
        "valid": not errors,
        "source_file_count": len(source),
        "source_only_count": len(allowed_source_only),
        "wheel_projected_count": len(projected["wheel"]),
        "sdist_projected_count": len(projected["sdist"]),
        "errors": errors,
    }
    return payload


def generate_artifact_manifest(root: Path) -> dict[str, Any]:
    """Generate canonical source-to-wheel/sdist projections from build declarations."""
    root = root.resolve(strict=True)
    pyproject_path = root / "pyproject.toml"
    manifest_path = root / "MANIFEST.in"
    config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = config["project"]
    setuptools = config["tool"]["setuptools"]
    version = str(project["version"])
    distribution = _distribution_name(str(project["name"]))
    dist_info = f"{distribution}-{version}.dist-info"
    sdist_root = f"{distribution}-{version}"
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    wheel_sources: set[Path] = set()

    package_dirs = {
        str(key): str(value) for key, value in setuptools.get("package-dir", {}).items()
    }
    for package in setuptools.get("packages", ()):
        candidates = [
            key
            for key in package_dirs
            if package == key or package.startswith(key + ".")
        ]
        if not candidates:
            errors.append(f"package {package} has no declared source directory")
            continue
        prefix = max(candidates, key=len)
        suffix = package.removeprefix(prefix).lstrip(".").replace(".", "/")
        source_dir = root / package_dirs[prefix] / suffix
        if not source_dir.is_dir():
            errors.append(
                f"package source directory is missing: {source_dir.relative_to(root).as_posix()}"
            )
            continue
        for source in sorted(
            source_dir.glob("*.py"), key=lambda item: item.name.casefold()
        ):
            installed = package.replace(".", "/") + "/" + source.name
            records.append(_record(root, source, installed, "wheel"))
            wheel_sources.add(source.resolve(strict=True))

    declared_packages = {str(package) for package in setuptools.get("packages", ())}
    for package, patterns in setuptools.get("package-data", {}).items():
        package = str(package)
        if package not in declared_packages:
            errors.append(f"package-data targets undeclared package: {package}")
            continue
        candidates = [
            key
            for key in package_dirs
            if package == key or package.startswith(key + ".")
        ]
        if not candidates:
            errors.append(f"package-data package {package} has no source directory")
            continue
        prefix = max(candidates, key=len)
        suffix = package.removeprefix(prefix).lstrip(".").replace(".", "/")
        source_dir = root / package_dirs[prefix] / suffix
        for pattern in patterns:
            matches = sorted(
                (
                    path
                    for path in source_dir.glob(str(pattern))
                    if path.is_file() and not path.is_symlink()
                ),
                key=lambda item: item.as_posix().casefold(),
            )
            if not matches:
                errors.append(
                    f"required package-data pattern matched no files: {package}:{pattern}"
                )
            for source in matches:
                relative = source.relative_to(source_dir).as_posix()
                installed = f"{package.replace('.', '/')}/{relative}"
                records.append(_record(root, source, installed, "wheel"))
                wheel_sources.add(source.resolve(strict=True))

    data_prefix = f"{distribution}-{version}.data/data"
    for target, patterns in setuptools.get("data-files", {}).items():
        for pattern in patterns:
            matches = sorted(
                (
                    path
                    for path in root.glob(str(pattern))
                    if path.is_file() and not path.is_symlink()
                ),
                key=lambda item: item.as_posix().casefold(),
            )
            if not matches:
                errors.append(f"required data-file pattern matched no files: {pattern}")
            for source in matches:
                installed = f"{data_prefix}/{str(target).strip('/')}/{source.name}"
                records.append(_record(root, source, installed, "wheel"))
                wheel_sources.add(source.resolve(strict=True))

    for declared in project.get("license-files", ()):
        source = root / str(declared)
        if not source.is_file() or source.is_symlink():
            errors.append(f"required license file is missing or unsafe: {declared}")
            continue
        records.append(
            _record(root, source, f"{dist_info}/licenses/{source.name}", "wheel")
        )
        wheel_sources.add(source.resolve(strict=True))

    try:
        sdist_sources = _manifest_sources(root, manifest_path) | wheel_sources
    except (OSError, ValueError) as error:
        sdist_sources = set(wheel_sources)
        errors.append(str(error))
    for source in sorted(
        sdist_sources, key=lambda item: item.relative_to(root).as_posix().casefold()
    ):
        installed = f"{sdist_root}/{source.relative_to(root).as_posix()}"
        records.append(_record(root, source, installed, "sdist"))

    collisions: dict[tuple[str, str], str] = {}
    for record in records:
        key = (record["package_target"], record["installed_path"])
        prior = collisions.get(key)
        if prior is not None and prior != record["source_path"]:
            errors.append(
                f"artifact projection collision at {key[1]}: {prior} and {record['source_path']}"
            )
        collisions[key] = record["source_path"]
    records.sort(
        key=lambda item: (
            item["package_target"],
            item["installed_path"].casefold(),
            item["source_path"],
        )
    )
    skill_source_only: set[str] = set()
    policy_path = root / "policies/release-artifact-policy.json"
    if policy_path.is_file():
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        skill_source_only = set(map(str, policy.get("skill_source_only", ())))
    skill_projection = verify_commissioned_skill_projection(
        root,
        {"records": records},
        source_only=skill_source_only,
    )
    errors.extend(skill_projection["errors"])
    payload = {
        "schema_version": "1.0",
        "distribution_model": "lean-runtime-wheel-complete-sdist",
        "project": project["name"],
        "version": version,
        "records": records,
        "allowed_generated": {
            "wheel": [
                f"{dist_info}/METADATA",
                f"{dist_info}/WHEEL",
                f"{dist_info}/entry_points.txt",
                f"{dist_info}/top_level.txt",
                f"{dist_info}/RECORD",
            ],
            "sdist": [
                f"{sdist_root}/PKG-INFO",
                f"{sdist_root}/setup.cfg",
                f"{sdist_root}/{distribution}.egg-info/*",
            ],
        },
        "skill_projection": skill_projection,
        "errors": sorted(set(errors)),
    }
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != "errors"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        **payload,
        "valid": not errors,
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def verify_declared_projection_duplicates(
    manifest: Mapping[str, Any],
    wheel_entries: Mapping[str, Mapping[str, Any]] | None = None,
    sdist_entries: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    entries_by_target = {"wheel": wheel_entries or {}, "sdist": sdist_entries or {}}
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    errors: list[str] = []
    for record in manifest.get("records", ()):
        grouped.setdefault(str(record["source_path"]), []).append(record)
    duplicate_count = 0
    for source, records in grouped.items():
        if len(records) < 2:
            continue
        duplicate_count += 1
        hashes = {str(record.get("source_sha256")) for record in records}
        if len(hashes) != 1:
            errors.append(f"declared projections disagree on source hash: {source}")
        for record in records:
            target = str(record["package_target"])
            archived = entries_by_target.get(target, {}).get(
                str(record["installed_path"])
            )
            if archived is not None and archived.get("sha256") != record.get(
                "source_sha256"
            ):
                errors.append(
                    f"declared projection hash mismatch: {target}:{record['installed_path']}"
                )
    return {
        "valid": not errors,
        "duplicate_source_count": duplicate_count,
        "errors": errors,
    }


def verify_built_artifact(
    artifact: Path,
    manifest: Mapping[str, Any],
    *,
    package_target: str,
) -> dict[str, Any]:
    if package_target not in {"wheel", "sdist"}:
        raise ValueError(f"unsupported package target: {package_target}")
    inspected = (
        inspect_wheel(artifact)
        if package_target == "wheel"
        else inspect_sdist(artifact)
    )
    entries = {str(item["path"]): item for item in inspected["entries"]}
    expected = {
        str(record["installed_path"]): record
        for record in manifest.get("records", ())
        if record.get("package_target") == package_target
    }
    generated = tuple(
        str(pattern)
        for pattern in manifest.get("allowed_generated", {}).get(package_target, ())
    )
    errors = [*manifest.get("errors", ()), *inspected["errors"]]
    for path, record in expected.items():
        entry = entries.get(path)
        if entry is None:
            if record.get("required") is True:
                errors.append(f"required {package_target} resource is missing: {path}")
        elif entry.get("sha256") != record.get("source_sha256"):
            errors.append(f"{package_target} projection hash mismatch: {path}")
    for path in sorted(set(entries) - set(expected)):
        if not any(fnmatchcase(path, pattern) for pattern in generated):
            errors.append(f"undeclared {package_target} file: {path}")
    classes = sorted({str(record["artifact_type"]) for record in expected.values()})
    return {
        "valid": not errors,
        "package_target": package_target,
        "expected_count": len(expected),
        "observed_count": len(entries),
        "distribution_classes": classes,
        "entries": entries,
        "errors": errors,
    }


def file_record(path: Path, artifact_type: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "type": artifact_type,
        "filename": path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _safe_member(name: str) -> bool:
    value = PurePosixPath(name)
    return (
        bool(name)
        and not value.is_absolute()
        and ".." not in value.parts
        and "\\" not in name
    )


def _metadata_version(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("Version: "):
            return line.removeprefix("Version: ").strip()
    return None


def inspect_wheel(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    entries: list[dict[str, Any]] = []
    version = None
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append("wheel contains duplicate member names")
        for info in sorted(
            archive.infolist(), key=lambda item: item.filename.casefold()
        ):
            if info.is_dir():
                continue
            if not _safe_member(info.filename):
                errors.append(f"unsafe wheel member: {info.filename}")
                continue
            data = archive.read(info)
            entries.append(
                {
                    "path": info.filename,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            if info.filename.endswith(".dist-info/METADATA"):
                version = _metadata_version(data.decode("utf-8", errors="strict"))
    if version is None:
        errors.append("wheel metadata version is missing")
    return {
        "valid": not errors,
        "version": version,
        "entries": entries,
        "errors": errors,
    }


def inspect_sdist(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    entries: list[dict[str, Any]] = []
    version = None
    with tarfile.open(path, mode="r:gz") as archive:
        members = archive.getmembers()
        names = [item.name for item in members]
        if len(names) != len(set(names)):
            errors.append("sdist contains duplicate member names")
        for member in sorted(members, key=lambda item: item.name.casefold()):
            if not _safe_member(member.name):
                errors.append(f"unsafe sdist member: {member.name}")
                continue
            if member.issym() or member.islnk():
                errors.append(f"sdist link member is forbidden: {member.name}")
                continue
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            if stream is None:
                errors.append(f"cannot read sdist member: {member.name}")
                continue
            data = stream.read()
            entries.append(
                {
                    "path": member.name,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            if member.name.endswith("/PKG-INFO"):
                version = _metadata_version(data.decode("utf-8", errors="strict"))
    if version is None:
        errors.append("sdist metadata version is missing")
    return {
        "valid": not errors,
        "version": version,
        "entries": entries,
        "errors": errors,
    }


def build_release_artifacts_once(
    root: Path,
    output_dir: Path,
    *,
    python_executable: str,
    environment: Mapping[str, str],
    intermediate_quarantine: Path | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("release artifact staging directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        python_executable,
        "-m",
        "build",
        "--no-isolation",
        "--wheel",
        "--sdist",
        "--outdir",
        str(output_dir),
    ]
    process = runner(
        command,
        cwd=root,
        env=dict(environment),
        text=True,
        capture_output=True,
        timeout=300,
    )
    errors: list[str] = []
    if process.returncode:
        errors.append(
            f"release build failed with exit code {process.returncode}: {(process.stderr or '')[-2000:]}"
        )
    wheels = sorted(output_dir.glob("*.whl"))
    sdists = sorted(output_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        errors.append(
            f"release build produced wheels={len(wheels)} sdists={len(sdists)}"
        )
    artifacts = ([file_record(wheels[0], "wheel")] if len(wheels) == 1 else []) + (
        [file_record(sdists[0], "sdist")] if len(sdists) == 1 else []
    )
    manifest: dict[str, Any] | None = None
    verification: dict[str, Any] = {}
    if (root / "pyproject.toml").is_file() and (root / "MANIFEST.in").is_file():
        manifest = generate_artifact_manifest(root)
        errors.extend(manifest["errors"])
        if len(wheels) == 1:
            verification["wheel"] = verify_built_artifact(
                wheels[0], manifest, package_target="wheel"
            )
            errors.extend(verification["wheel"]["errors"])
        if len(sdists) == 1:
            verification["sdist"] = verify_built_artifact(
                sdists[0], manifest, package_target="sdist"
            )
            errors.extend(verification["sdist"]["errors"])
        if "wheel" in verification and "sdist" in verification:
            verification["projections"] = verify_declared_projection_duplicates(
                manifest,
                verification["wheel"]["entries"],
                verification["sdist"]["entries"],
            )
            errors.extend(verification["projections"]["errors"])
    intermediate_custody: dict[str, Any] | None = None
    intermediates_exist = (
        (root / "build").exists()
        or (root / "dist").exists()
        or any(root.glob("*.egg-info"))
    )
    if intermediates_exist:
        if intermediate_quarantine is None:
            errors.append(
                "release build left source-tree intermediates without a quarantine target"
            )
        else:
            intermediate_custody = quarantine_build_intermediates(
                root, intermediate_quarantine
            )
            errors.extend(intermediate_custody["errors"])
    return {
        "valid": not errors,
        "build_invocations": 1,
        "command": command,
        "artifacts": artifacts,
        "artifact_manifest": manifest,
        "artifact_manifest_sha256": manifest.get("manifest_sha256")
        if manifest
        else None,
        "artifact_verification": verification,
        "intermediate_custody": intermediate_custody,
        "errors": errors,
    }


def verify_artifact_records(
    directory: Path, records: list[Mapping[str, object]]
) -> dict[str, Any]:
    root = directory.resolve(strict=True)
    errors: list[str] = []
    seen: set[str] = set()
    for record in records:
        filename = str(record.get("filename", ""))
        if not filename or Path(filename).name != filename or filename in seen:
            errors.append(f"invalid or duplicate artifact filename: {filename}")
            continue
        seen.add(filename)
        path = root / filename
        if not path.is_file() or path.is_symlink():
            errors.append(f"artifact is missing or unsafe: {filename}")
            continue
        actual = file_record(path, str(record.get("type", "unknown")))
        if any(
            actual[key] != record.get(key)
            for key in ("filename", "type", "sha256", "size_bytes")
        ):
            errors.append(f"artifact bytes do not match certificate: {filename}")
    return {"valid": not errors, "artifact_count": len(records), "errors": errors}


def install_exact_wheel(
    wheel: Path,
    expected_sha256: str,
    environment_root: Path,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    wheel = wheel.resolve(strict=True)
    actual = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if actual != expected_sha256:
        return {
            "valid": False,
            "installed_wheel_sha256": None,
            "errors": ["wheel changed before installation"],
        }
    venv.EnvBuilder(with_pip=True).create(environment_root)
    python = environment_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    process = runner(
        [str(python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel)],
        cwd=environment_root,
        env=scrub_release_environment(),
        text=True,
        capture_output=True,
        timeout=300,
    )
    after = hashlib.sha256(wheel.read_bytes()).hexdigest()
    errors = []
    if process.returncode:
        errors.append(
            f"exact wheel installation failed: {(process.stderr or '')[-2000:]}"
        )
    if after != expected_sha256:
        errors.append("wheel changed during installation")
    return {
        "valid": not errors,
        "python_executable": str(python),
        "installed_wheel_sha256": expected_sha256 if not errors else None,
        "wheel_filename": wheel.name,
        "errors": errors,
    }


def bind_artifact_set(
    directory: Path,
    records: list[Mapping[str, object]],
    *,
    source_product_digest: str,
    version: str,
    source_root: Path | None = None,
) -> dict[str, Any]:
    verified = verify_artifact_records(directory, records)
    errors = list(verified["errors"])
    wheel_record = next((item for item in records if item.get("type") == "wheel"), None)
    sdist_record = next((item for item in records if item.get("type") == "sdist"), None)
    if wheel_record is None or sdist_record is None:
        errors.append("artifact set requires exactly one wheel and one sdist")
        return {
            "valid": False,
            "source_product_digest": source_product_digest,
            "errors": errors,
        }
    wheel = inspect_wheel(directory / str(wheel_record["filename"]))
    sdist = inspect_sdist(directory / str(sdist_record["filename"]))
    errors.extend(wheel["errors"])
    errors.extend(sdist["errors"])
    if wheel["version"] != version:
        errors.append("wheel metadata version does not match authoritative version")
    if sdist["version"] != version:
        errors.append("sdist metadata version does not match authoritative version")
    manifest = (
        generate_artifact_manifest(source_root) if source_root is not None else None
    )
    artifact_checks: dict[str, Any] = {}
    if manifest is not None:
        wheel_check = verify_built_artifact(
            directory / str(wheel_record["filename"]), manifest, package_target="wheel"
        )
        sdist_check = verify_built_artifact(
            directory / str(sdist_record["filename"]), manifest, package_target="sdist"
        )
        projection_check = verify_declared_projection_duplicates(
            manifest, wheel_check["entries"], sdist_check["entries"]
        )
        artifact_checks = {
            "wheel": wheel_check,
            "sdist": sdist_check,
            "projections": projection_check,
        }
        errors.extend(
            [
                *wheel_check["errors"],
                *sdist_check["errors"],
                *projection_check["errors"],
            ]
        )
    return {
        "valid": not errors,
        "version": version,
        "source_product_digest": source_product_digest,
        "wheel_manifest_sha256": hashlib.sha256(
            json.dumps(wheel["entries"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "sdist_manifest_sha256": hashlib.sha256(
            json.dumps(sdist["entries"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "artifact_manifest_sha256": manifest.get("manifest_sha256")
        if manifest
        else None,
        "artifact_checks": artifact_checks,
        "wheel": wheel,
        "sdist": sdist,
        "errors": errors,
    }
