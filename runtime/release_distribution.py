"""Build, inspect, install, and verify one immutable release artifact set."""

from __future__ import annotations

from bisect import bisect_left
import hashlib
from email.parser import Parser
from fnmatch import fnmatchcase
from functools import lru_cache
import json
import os
import re
from pathlib import Path
import shlex
import subprocess
import tarfile
import tomllib
from typing import Any, Callable, Mapping
import venv
import zipfile
import zlib

from .archive_io import (
    ArchiveLimits,
    DEFAULT_LIMITS,
    member_identity,
    portable_member_name,
    read_archive_bytes,
    read_stream_bytes,
    reject_path_links,
    validated_sdist,
    validated_zip,
)
from .bounded_walk import WalkLimits, bounded_walk
from .json_io import (
    bounded_json_text,
    bounded_strings,
    read_bounded_bytes,
)
from .release_environment import scrub_release_environment


Runner = Callable[..., subprocess.CompletedProcess[str]]
SKILL_EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
SKILL_EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}


def _safe_pattern(value: Any) -> str:
    if type(value) is not str or not value or len(value) > 4096:
        raise ValueError("source pattern must be bounded relative text")
    portable_member_name(
        value.replace("*", "x").replace("?", "x"), allow_directory=False
    )
    if len(value.split("/")) > 64:
        raise ValueError("source pattern depth exceeded")
    return value


def _declaration_strings(
    values: Any, *, max_items: int = 1024, max_item_bytes: int = 4096
) -> tuple[str, ...]:
    if type(values) is not list:
        raise ValueError("source declaration must be a string array")
    result = bounded_strings(
        values,
        max_items=max_items,
        max_item_bytes=max_item_bytes,
        max_bytes=1024 * 1024,
    )
    if len(result) != len(values):
        raise ValueError("duplicate source declaration")
    return result


def _glob_match(path: str, pattern: str, *, directory: bool = False) -> bool:
    """Portable component matching; '*' never crosses a path separator."""
    parts = tuple(path.casefold().split("/"))
    glob = tuple(pattern.casefold().split("/"))

    @lru_cache(maxsize=4096)
    def matches(i, j):
        if i == len(parts):
            return (
                j < len(glob) if directory else all(part == "**" for part in glob[j:])
            )
        if j == len(glob):
            return False
        if glob[j] == "**":
            return matches(i, j + 1) or matches(i + 1, j)
        return fnmatchcase(parts[i], glob[j]) and matches(i + 1, j + 1)

    return matches(0, 0)


def _manifest_rules(text: str) -> list[tuple[bool, str]]:
    rules = [(True, "pyproject.toml"), (True, "MANIFEST.in")]
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = shlex.split(line)
        command, arguments = parts[0], parts[1:]
        if command in ("include", "exclude") and arguments:
            values = [_safe_pattern(value) for value in arguments]
        elif command in ("recursive-include", "recursive-exclude") and len(arguments) >= 2:
            base = _safe_pattern(arguments[0])
            values = [_safe_pattern(base + "/**/" + pattern) for pattern in arguments[1:]]
        elif command == "prune" and len(arguments) == 1:
            values = [_safe_pattern(arguments[0]) + "/**"]
        else:
            raise ValueError("unsupported or malformed MANIFEST.in directive")
        rules.extend((command in ("include", "recursive-include"), value) for value in values)
        if len(rules) > 4096:
            raise ValueError("source manifest pattern budget exceeded")
    return rules


def _manifest_patterns(text: str) -> tuple[list[str], list[str]]:
    rules = _manifest_rules(text)
    return ([pattern for include, pattern in rules if include],
            [pattern for include, pattern in rules if not include])


def _manifest_selected(path, rules):
    selected = False
    for include, pattern in rules:
        if _glob_match(path, pattern):
            selected = include
    return selected


def _pattern_intersects_subtree(pattern, prefix):
    literal = re.split(r"[*?\[]", pattern, maxsplit=1)[0].casefold()
    return literal.startswith(prefix.casefold()) or _glob_match(
        prefix.rstrip("/"), pattern, directory=True
    )


def _validate_control_projection(policy, rules, requests):
    paths = tuple(policy.get("control_output_paths", []))
    prefixes = tuple(policy.get("control_output_prefixes", []))
    for path in paths:
        if _manifest_selected(path, rules):
            raise ValueError("sdist declares a mutable control output: " + path)
    for prefix in prefixes:
        # Exact whole-subtree exclusions permit safe pre-traversal pruning.
        exclusions = [i for i, (include, pattern) in enumerate(rules)
                      if not include and pattern.casefold() == prefix.casefold() + "**"]
        relevant = any(include and _pattern_intersects_subtree(pattern, prefix)
                       for include, pattern in rules)
        if relevant and (not exclusions or any(
            include and _pattern_intersects_subtree(pattern, prefix)
            for include, pattern in rules[exclusions[-1] + 1:]
        )):
            raise ValueError("sdist must exclude the complete mutable control subtree: " + prefix)
    for pattern, _target, _base, _kind in requests:
        if any(_glob_match(path, pattern) for path in paths) or any(
            _pattern_intersects_subtree(pattern, prefix) for prefix in prefixes
        ):
            raise ValueError("required wheel declaration intersects mutable control output: " + pattern)
    if any(path.casefold().startswith('.px/skills/') for path in paths) or any(
        _pattern_intersects_subtree('.px/skills/**', prefix) for prefix in prefixes
    ):
        raise ValueError("control policy intersects commissioned skill inputs")
    return frozenset(path.casefold() for path in paths), tuple(prefix.casefold() for prefix in prefixes)


class _ProjectionInputs:
    """One bounded metadata inventory and one byte image per selected source."""

    def __init__(
        self,
        root: Path,
        patterns: list[str],
        controls: dict[str, bytearray],
        limits: ArchiveLimits,
        *, control_paths=frozenset(), control_prefixes=(),
    ):
        self.root = root
        self.limits = limits
        self.controls = controls
        if len(patterns) > 8192:
            raise ValueError("source projection pattern budget exceeded")
        ignored = {
            ".git",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "quarantine",
            ".quarantine",
            "_quarantine",
            "repo_quarantine",
        }

        def exclude(relative):
            folded = relative.casefold()
            if folded in control_paths or any(
                folded == prefix.rstrip('/') or folded.startswith(prefix)
                for prefix in control_prefixes
            ):
                return True
            path = root / relative
            directory = path.is_dir()
            parts = relative.casefold().split("/")
            directories = parts if directory else parts[:-1]
            # Custody directories are exact identities. Authored capabilities
            # such as quarantine-external-tools remain ordinary source inputs.
            if any(part in ignored for part in directories):
                return True
            if (
                parts[:2] == [".px", "skills"]
                and path.suffix.casefold() in SKILL_EXCLUDED_SUFFIXES
            ):
                return True
            return not any(
                _glob_match(relative, pattern, directory=directory)
                for pattern in patterns
            )

        tree = bounded_walk(
            root,
            limits=WalkLimits(
                max_files=limits.max_members,
                max_depth=64,
                max_bytes=limits.max_expanded_bytes,
                max_entries=limits.max_members * 8,
                max_directories=limits.max_members,
            ),
            exclude=exclude,
        )
        self.files = {entry.relative: entry for entry in tree.files}
        self.facts = {}
        self.remaining = limits.max_expanded_bytes
        seen = set()
        for relative, entry in self.files.items():
            identity = member_identity(relative)
            if identity in seen:
                raise ValueError("source inventory contains a portable path alias")
            seen.add(identity)
            if entry.size > limits.max_member_bytes:
                raise ValueError("source projection member byte budget exceeded")
        # Build only after complete portable identity validation. Preserve the
        # matcher's casefold semantics without introducing Unicode normalization.
        self._literal_paths = {path.casefold(): path for path in self.files}
        self._path_keys = sorted(self._literal_paths)
        for relative in controls:
            if relative not in self.files:
                raise ValueError(
                    "source control metadata was excluded from its inventory"
                )
            self.acquire(relative)

    def matching(self, pattern: str) -> list[str]:
        wildcard = re.search(r"[*?\[]", pattern)
        if wildcard is None:
            path = self._literal_paths.get(pattern.casefold())
            return [] if path is None else [path]
        prefix = pattern[: wildcard.start()].casefold()
        result = []
        for index in range(bisect_left(self._path_keys, prefix), len(self._path_keys)):
            key = self._path_keys[index]
            if not key.startswith(prefix):
                break
            path = self._literal_paths[key]
            if _glob_match(path, pattern):
                result.append(path)
        return result

    def acquire(self, relative: str) -> dict[str, Any]:
        if relative in self.facts:
            return self.facts[relative]
        entry = self.files[relative]
        if entry.size > self.limits.max_member_bytes or entry.size > self.remaining:
            raise ValueError("source projection acquisition byte budget exceeded")
        if relative in self.controls:
            raw = self.controls[relative]
        else:
            reject_path_links(entry.path)
            if not entry.path.resolve().is_relative_to(self.root):
                raise ValueError("source projection path escaped its root")
            with entry.path.open("rb") as stream:
                raw = read_stream_bytes(
                    stream,
                    max_bytes=min(self.limits.max_member_bytes, self.remaining),
                    expected_size=entry.size,
                )
        if len(raw) != entry.size or len(raw) > self.remaining:
            raise ValueError("source projection changed during acquisition")
        self.remaining -= len(raw)
        result = {
            "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
        self.facts[relative] = result
        return result


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
    reject_path_links(source)
    canonical_root = root.resolve(strict=True)
    canonical = source.resolve(strict=True)
    if not canonical.is_relative_to(canonical_root):
        raise ValueError("projection source escapes root")
    relative = canonical.relative_to(canonical_root).as_posix()
    portable_member_name(installed_path, allow_directory=False)
    data = read_archive_bytes(source)
    artifact_class, owner = _artifact_class(relative)
    return {
        "source_path": relative,
        "installed_path": installed_path,
        "artifact_type": artifact_class,
        "owner": owner,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_size_bytes": len(data),
        "required": True,
        "package_target": target,
        "designation": "authoritative",
        "generated": False,
    }


def _manifest_sources(root: Path, manifest_path: Path) -> set[Path]:
    reject_path_links(root)
    reject_path_links(manifest_path)
    root = root.resolve(strict=True)
    if not manifest_path.resolve().is_relative_to(root):
        raise ValueError("source manifest escapes root")
    data = read_bounded_bytes(manifest_path, max_bytes=1024 * 1024)
    manifest_rules = _manifest_rules(data.decode("utf-8"))
    included = [pattern for include, pattern in manifest_rules if include]
    pruned = tuple(pattern[:-2].casefold() for index, (include, pattern) in enumerate(manifest_rules)
        if not include and pattern.endswith('/**') and not re.search(r"[*?\[]", pattern[:-3])
        and not any(later_include and _pattern_intersects_subtree(later_pattern, pattern[:-2])
                    for later_include, later_pattern in manifest_rules[index + 1:]))
    inputs = _ProjectionInputs(root, included, {}, DEFAULT_LIMITS, control_prefixes=pruned)
    return {
        root / path
        for path in inputs.files
        if _manifest_selected(path, manifest_rules)
    }


def commissioned_skill_sources(root: Path) -> dict[str, dict[str, object]]:
    reject_path_links(root)
    inputs = _ProjectionInputs(
        root.resolve(strict=True), [".px/skills/**"], {}, DEFAULT_LIMITS
    )
    return {path: inputs.acquire(path) for path in sorted(inputs.files)}


def _verify_skill_projection(source, manifest, source_only):
    allowed_source_only = set(
        bounded_strings(
            source_only, max_items=4096, max_item_bytes=4096, max_bytes=1024 * 1024
        )
    )
    projected = {"wheel": {}, "sdist": {}}
    errors = []
    records = manifest.get("records")
    if type(records) is not list or len(records) > 100_000:
        raise ValueError("skill projection records require a bounded list")
    for record in records:
        if type(record) is not dict:
            raise ValueError("skill projection record must be an object")
        source_path = record.get("source_path", "")
        target = record.get("package_target", "")
        if type(source_path) is not str or type(target) is not str:
            raise ValueError("skill projection identity must be text")
        if source_path.startswith(".px/skills/"):
            portable_member_name(source_path, allow_directory=False)
            if target not in projected:
                errors.append("skill projection target is invalid: " + source_path)
                continue
            projected[target].setdefault(source_path, []).append(record)
    for path, fact in source.items():
        for target in ("wheel", "sdist"):
            expected = 0 if target == "wheel" and path in allowed_source_only else 1
            matches = projected[target].get(path, [])
            if len(matches) != expected:
                errors.append(
                    f"skill projection count mismatch: {target}:{path}:{len(matches)}"
                )
                continue
            if matches and matches[0].get("source_sha256") != fact["sha256"]:
                errors.append(f"skill projection hash mismatch: {target}:{path}")
        wheel = projected["wheel"].get(path, [])
        if wheel and (
            type(wheel[0].get("installed_path")) is not str
            or not wheel[0]["installed_path"].endswith("/" + path)
        ):
            errors.append("skill wheel path is not equivalent: " + path)
    for target in ("wheel", "sdist"):
        errors.extend(
            f"unknown skill projection source: {target}:{path}"
            for path in sorted(set(projected[target]) - source.keys())
        )
    errors.extend(
        "source-only policy path does not exist: " + path
        for path in sorted(allowed_source_only - source.keys())
    )
    return {
        "valid": not errors,
        "source_file_count": len(source),
        "source_only_count": len(allowed_source_only),
        "wheel_projected_count": len(projected["wheel"]),
        "sdist_projected_count": len(projected["sdist"]),
        "errors": errors,
    }


def verify_commissioned_skill_projection(
    root: Path, manifest: Mapping[str, Any], *, source_only: set[str] | None = None
) -> dict[str, Any]:
    # A failed producer has no projection denominator to compare. Do not turn
    # that failure into either missing-member noise or vacuous empty success.
    errors = []
    if not isinstance(manifest, Mapping):
        errors = ["skill projection manifest must be an object"]
    elif "valid" in manifest:
        if type(manifest["valid"]) is not bool:
            errors = ["artifact manifest validity must be boolean"]
        else:
            try:
                supplied_errors = manifest.get("errors", [])
                if type(supplied_errors) is not list:
                    raise ValueError("artifact manifest errors must be a bounded list")
                errors = list(
                    bounded_strings(
                        supplied_errors,
                        max_items=1024,
                        max_item_bytes=4096,
                        max_bytes=65536,
                    )
                )
            except ValueError as error:
                errors = [str(error)]
            if not manifest["valid"] and not errors:
                errors = ["artifact manifest generation failed"]
    if errors:
        return {
            "valid": False,
            "source_evaluated": False,
            "source_file_count": None,
            "source_only_count": None,
            "wheel_projected_count": None,
            "sdist_projected_count": None,
            "errors": errors,
        }
    result = _verify_skill_projection(
        commissioned_skill_sources(root), manifest, source_only or set()
    )
    return {**result, "source_evaluated": True}


def generate_artifact_manifest(
    root: Path, *, limits: ArchiveLimits = DEFAULT_LIMITS
) -> dict[str, Any]:
    """Plan every projection before acquiring one bounded image per source."""
    try:
        return _generate_artifact_manifest(root, limits)
    except (OSError, KeyError, TypeError, ValueError) as error:
        return {
            "schema_version": "1.0",
            "valid": False,
            "records": [],
            "manifest_sha256": None,
            "errors": [str(error)],
        }


def _generate_artifact_manifest(root: Path, limits: ArchiveLimits) -> dict[str, Any]:
    reject_path_links(root)
    root = root.resolve(strict=True)
    controls = {}
    remaining_controls = limits.max_expanded_bytes
    for name in ("pyproject.toml", "MANIFEST.in"):
        path = root / name
        reject_path_links(path)
        if remaining_controls < 1:
            raise ValueError("source control metadata byte budget exhausted")
        controls[name] = read_bounded_bytes(
            path, max_bytes=min(1024 * 1024, remaining_controls)
        )
        remaining_controls -= len(controls[name])
    config = tomllib.loads(controls["pyproject.toml"].decode("utf-8"))
    project = config["project"]
    setuptools = config["tool"]["setuptools"]
    name, version = project["name"], project["version"]
    if (
        type(name) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) is None
        or type(version) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+!]{0,127}", version) is None
    ):
        raise ValueError("project name/version must be bounded canonical text")
    distribution = _distribution_name(name)
    manifest_rules = _manifest_rules(controls["MANIFEST.in"].decode("utf-8"))
    included = [pattern for include, pattern in manifest_rules if include]
    patterns = [*included, ".px/skills/**", "policies/release-artifact-policy.json"]
    packages = _declaration_strings(setuptools.get("packages", []), max_item_bytes=256)
    directories = setuptools.get("package-dir", {})
    if type(directories) is not dict or len(directories) > 1024:
        raise ValueError("package directories must be a bounded object")
    for key, value in directories.items():
        if (
            type(key) is not str
            or key
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", key) is None
        ):
            raise ValueError("package directory key is malformed")
        if value != ".":
            portable_member_name(value, allow_directory=False)
    package_sources = {}
    requests = []
    for package in packages:
        if (
            re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", package
            )
            is None
        ):
            raise ValueError("package name is malformed")
        candidates = [
            key
            for key in directories
            if not key or package == key or package.startswith(key + ".")
        ]
        if not candidates:
            raise ValueError("package has no declared source directory: " + package)
        prefix = max(candidates, key=len)
        suffix = package[len(prefix) :].lstrip(".").replace(".", "/")
        base = "/".join(
            part for part in (directories[prefix], suffix) if part and part != "."
        )
        if base:
            _safe_pattern(base)
        package_sources[package] = base
        pattern = (base + "/" if base else "") + "*.py"
        requests.append((pattern, package.replace(".", "/"), base, "package"))
        patterns.append(pattern)
    package_data = setuptools.get("package-data", {})
    if type(package_data) is not dict or len(package_data) > 1024:
        raise ValueError("package-data must be a bounded object")
    for package, values in package_data.items():
        if package not in package_sources:
            raise ValueError("package-data targets undeclared package")
        base = package_sources[package]
        for pattern in _declaration_strings(values):
            joined = (base + "/" if base else "") + _safe_pattern(pattern)
            patterns.append(joined)
            requests.append((joined, package.replace(".", "/"), base, "package-data"))
    data_files = setuptools.get("data-files", {})
    if type(data_files) is not dict or len(data_files) > 4096:
        raise ValueError("data-files must be a bounded object")
    for target, values in data_files.items():
        portable_member_name(target, allow_directory=False)
        for pattern in _declaration_strings(values):
            pattern = _safe_pattern(pattern)
            patterns.append(pattern)
            requests.append(
                (
                    pattern,
                    f"{distribution}-{version}.data/data/{target}",
                    "",
                    "data-files",
                )
            )
    for license_path in _declaration_strings(
        project.get("license-files", []), max_items=64
    ):
        pattern = _safe_pattern(license_path)
        patterns.append(pattern)
        requests.append(
            (pattern, f"{distribution}-{version}.dist-info/licenses", "", "license")
        )
    source_only = ()
    policy_value = {}
    policy = "policies/release-artifact-policy.json"
    if (root / policy).exists():
        reject_path_links(root / policy)
        if remaining_controls < 1:
            raise ValueError("source control metadata byte budget exhausted")
        controls[policy] = read_bounded_bytes(
            root / policy, max_bytes=min(1024 * 1024, remaining_controls)
        )
        from .release_artifacts import decode_release_policy
        policy_value = decode_release_policy(controls[policy])
        source_only = _declaration_strings(policy_value.get("skill_source_only", []), max_items=4096)
    control_paths, control_prefixes = _validate_control_projection(policy_value, manifest_rules, requests)
    inputs = _ProjectionInputs(root, patterns, controls, limits,
                               control_paths=control_paths, control_prefixes=control_prefixes)
    planned = []
    projected = set()
    wheel_sources = set()
    planned_bytes = 0

    def add(source, installed, target):
        nonlocal planned_bytes
        portable_member_name(installed, allow_directory=False)
        identity = (target, member_identity(installed))
        if identity in projected:
            raise ValueError("duplicate artifact projection or portable path alias")
        projected.add(identity)
        artifact_class, owner = _artifact_class(source)
        skeleton = {
            "source_path": source,
            "installed_path": installed,
            "artifact_type": artifact_class,
            "owner": owner,
            "source_sha256": "0" * 64,
            "source_size_bytes": inputs.files[source].size,
            "required": True,
            "package_target": target,
            "designation": "authoritative",
            "generated": False,
        }
        planned_bytes += (
            len(json.dumps(skeleton, sort_keys=True, separators=(",", ":")).encode())
            + 1
        )
        if planned_bytes > 30 * 1024 * 1024:
            raise ValueError("source projection manifest byte budget exceeded")
        planned.append((source, installed, target))
        if len(planned) > min(100_000, 2 * limits.max_members):
            raise ValueError("source projection record budget exceeded")

    for pattern, target, base, kind in requests:
        matches = inputs.matching(pattern)
        if not matches:
            raise ValueError("required projection pattern matched no files: " + pattern)
        for source in matches:
            relative = source[len(base) + 1 :] if base else source
            installed = (
                target
                + "/"
                + (
                    relative
                    if kind in ("package", "package-data")
                    else source.rsplit("/", 1)[-1]
                )
            )
            add(source, installed, "wheel")
            wheel_sources.add(source)
    for source in wheel_sources:
        decisions = [include for include, pattern in manifest_rules if _glob_match(source, pattern)]
        if decisions and decisions[-1] is False:
            raise ValueError("sdist excludes a required wheel source: " + source)
    sdist_sources = {
        path
        for path in inputs.files
        if _manifest_selected(path, manifest_rules)
    } | wheel_sources
    if not {"pyproject.toml", "MANIFEST.in"} <= sdist_sources:
        raise ValueError("sdist projection omitted required source controls")
    for source in sorted(sdist_sources, key=lambda value: (value.casefold(), value)):
        add(source, f"{distribution}-{version}/{source}", "sdist")
    # The source universe is fully bounded before any payload read. Files omitted
    # from projections still belong to the commissioned-skill denominator.
    for entry in inputs.files.values():
        if entry.size > limits.max_member_bytes:
            raise ValueError("source projection member byte budget exceeded")
    skill_paths = {path for path in inputs.files if path.startswith(".px/skills/")}
    selected = {source for source, _, _ in planned} | skill_paths
    for path in sorted(selected):
        inputs.acquire(path)
    records = []
    for source, installed, target in planned:
        fact = inputs.facts[source]
        artifact_class, owner = _artifact_class(source)
        records.append(
            {
                "source_path": source,
                "installed_path": installed,
                "artifact_type": artifact_class,
                "owner": owner,
                "source_sha256": fact["sha256"],
                "source_size_bytes": fact["size_bytes"],
                "required": True,
                "package_target": target,
                "designation": "authoritative",
                "generated": False,
            }
        )
    records.sort(
        key=lambda item: (
            item["package_target"],
            item["installed_path"].casefold(),
            item["source_path"],
        )
    )
    skill_projection = _verify_skill_projection(
        {path: inputs.facts[path] for path in skill_paths},
        {"records": records},
        source_only,
    )
    payload = {
        "schema_version": "1.0",
        "distribution_model": "lean-runtime-wheel-complete-sdist",
        "project": name,
        "version": version,
        "records": records,
        "allowed_generated": _generated_file_policy(distribution, version),
        "skill_projection": skill_projection,
        "errors": sorted(set(skill_projection["errors"])),
    }
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != "errors"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    result = {
        **payload,
        "valid": not payload["errors"],
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    intrinsic = validate_artifact_manifest(result)
    if not intrinsic["valid"]:
        result["valid"] = False
        result["errors"] = sorted(set([*result["errors"], *intrinsic["errors"]]))
    return result


def _generated_file_policy(distribution: str, version: str) -> dict[str, list[str]]:
    dist_info = f"{distribution}-{version}.dist-info"
    sdist_root = f"{distribution}-{version}"
    return {
        "wheel": [
            f"{dist_info}/{name}"
            for name in (
                "METADATA",
                "WHEEL",
                "entry_points.txt",
                "top_level.txt",
                "RECORD",
            )
        ],
        "sdist": [
            f"{sdist_root}/PKG-INFO",
            f"{sdist_root}/setup.cfg",
            f"{sdist_root}/{distribution}.egg-info/*",
        ],
    }


def validate_artifact_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Check bounded frozen input structure and arithmetic, not its provenance."""
    errors = []
    observed_digest = None
    records = []
    try:
        if type(manifest) is not dict:
            raise ValueError("artifact manifest must be a JSON object")
        bounded_json_text(manifest, max_bytes=32 * 1024 * 1024)
        canonical = json.dumps(
            {
                key: value
                for key, value in manifest.items()
                if key not in {"errors", "valid", "manifest_sha256"}
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        observed_digest = hashlib.sha256(canonical).hexdigest()
        fields = {
            "schema_version",
            "distribution_model",
            "project",
            "version",
            "records",
            "allowed_generated",
            "skill_projection",
            "errors",
            "valid",
            "manifest_sha256",
        }
        if (
            set(manifest) != fields
            or manifest["schema_version"] != "1.0"
            or manifest["distribution_model"] != "lean-runtime-wheel-complete-sdist"
        ):
            raise ValueError("artifact manifest schema or fields are unsupported")
        project, version = manifest["project"], manifest["version"]
        if (
            type(project) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", project) is None
            or type(version) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+!]{0,127}", version) is None
        ):
            raise ValueError("artifact manifest project or version is malformed")
        records = manifest["records"]
        if type(records) is not list or not 1 <= len(records) <= 100_000:
            raise ValueError(
                "artifact manifest requires a bounded nonempty record denominator"
            )
        record_fields = {
            "source_path",
            "installed_path",
            "artifact_type",
            "owner",
            "source_sha256",
            "source_size_bytes",
            "required",
            "package_target",
            "designation",
            "generated",
        }
        projections = set()
        sources = {}
        skills = {"wheel": set(), "sdist": set()}
        targets = set()
        for record in records:
            if type(record) is not dict or set(record) != record_fields:
                raise ValueError("artifact manifest record fields are malformed")
            for field in ("source_path", "installed_path"):
                portable_member_name(record[field], allow_directory=False)
            target = record["package_target"]
            if type(target) is not str or target not in ("wheel", "sdist"):
                raise ValueError("artifact manifest record target is invalid")
            targets.add(target)
            identity = (target, member_identity(record["installed_path"]))
            if identity in projections:
                raise ValueError("duplicate artifact projection or portable path alias")
            projections.add(identity)
            size, digest = record["source_size_bytes"], record["source_sha256"]
            if (
                type(size) is not int
                or not 0 <= size <= DEFAULT_LIMITS.max_expanded_bytes
                or type(digest) is not str
                or re.fullmatch(r"[a-f0-9]{64}", digest) is None
                or type(record["required"]) is not bool
                or type(record["generated"]) is not bool
            ):
                raise ValueError(
                    "artifact record requires strict sizes, digests and booleans"
                )
            if record["designation"] != "authoritative" or record["generated"]:
                raise ValueError(
                    "source projection records must be authoritative source bytes"
                )
            artifact_type, owner = _artifact_class(record["source_path"])
            if record["artifact_type"] != artifact_type or record["owner"] != owner:
                raise ValueError(
                    "artifact source class or owner does not match its declared path"
                )
            key = member_identity(record["source_path"])
            value = (record["source_path"], digest, size)
            if key in sources and sources[key] != value:
                raise ValueError(
                    "source projections disagree on identity, bytes or hash"
                )
            sources[key] = value
            if record["source_path"].startswith(".px/skills/"):
                skills[target].add(key)
        if (
            targets != {"wheel", "sdist"}
            or sum(value[2] for value in sources.values())
            > DEFAULT_LIMITS.max_expanded_bytes
        ):
            raise ValueError(
                "artifact manifest target or aggregate source-byte denominator is incomplete"
            )
        policy = manifest["allowed_generated"]
        allowed = _generated_file_policy(_distribution_name(project), version)
        if type(policy) is not dict or set(policy) != {"wheel", "sdist"}:
            raise ValueError("artifact generated-file policy is malformed")
        for target in ("wheel", "sdist"):
            values = policy[target]
            if (
                type(values) is not list
                or not 1 <= len(values) <= len(allowed[target])
                or any(type(value) is not str for value in values)
                or len(values) != len(set(values))
                or not set(values) <= set(allowed[target])
            ):
                raise ValueError(
                    "artifact generated-file policy exceeds declared metadata owners"
                )
        proof = manifest["skill_projection"]
        count_fields = {
            "source_file_count",
            "source_only_count",
            "wheel_projected_count",
            "sdist_projected_count",
        }
        if type(proof) is not dict or set(proof) != count_fields | {"valid", "errors"}:
            raise ValueError("artifact skill projection proof is incomplete")
        if (
            proof["valid"] is not True
            or proof["errors"] != []
            or any(
                type(proof[key]) is not int or proof[key] < 0 for key in count_fields
            )
            or not skills["wheel"] <= skills["sdist"]
            or proof["wheel_projected_count"] != len(skills["wheel"])
            or proof["sdist_projected_count"] != len(skills["sdist"])
            or proof["source_file_count"] != len(skills["sdist"])
            or proof["source_only_count"] != len(skills["sdist"] - skills["wheel"])
        ):
            raise ValueError("artifact skill projection denominator is inconsistent")
        if manifest["valid"] is not True or manifest["errors"] != []:
            raise ValueError("artifact manifest generation is not valid")
    except (KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
    if (
        type(manifest) is dict
        and observed_digest is not None
        and manifest.get("manifest_sha256") != observed_digest
    ):
        errors.append("artifact manifest intrinsic digest mismatch")
    return {
        "valid": not errors,
        "manifest_sha256": observed_digest,
        "record_count": len(records) if type(records) is list else 0,
        "errors": errors,
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
    intrinsic = validate_artifact_manifest(manifest)
    if not intrinsic["valid"]:
        return {
            "valid": False,
            "package_target": package_target,
            "expected_count": 0,
            "observed_count": 0,
            "distribution_classes": [],
            "entries": {},
            "errors": intrinsic["errors"],
        }
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
        else:
            if entry.get("sha256") != record.get("source_sha256"):
                errors.append(f"{package_target} projection hash mismatch: {path}")
            if entry.get("size_bytes") != record.get("source_size_bytes"):
                errors.append(f"{package_target} projection size mismatch: {path}")
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


def file_record(
    path: Path, artifact_type: str, *, limits: ArchiveLimits = DEFAULT_LIMITS
) -> dict[str, Any]:
    if artifact_type not in ("wheel", "sdist"):
        raise ValueError("unsupported release artifact type")
    portable_member_name(path.name, allow_directory=False)
    suffix = ".whl" if artifact_type == "wheel" else ".tar.gz"
    if not path.name.endswith(suffix):
        raise ValueError("artifact filename does not match its declared type")
    data = read_archive_bytes(path, limits)
    return {
        "type": artifact_type,
        "filename": path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _safe_member(name: str) -> bool:
    try:
        portable_member_name(name)
        return True
    except (TypeError, ValueError):
        return False


def _metadata_version(text: str) -> str | None:
    values = Parser().parsestr(text, headersonly=True).get_all("Version", [])
    return str(values[0]).strip() if len(values) == 1 else None


def _archive_identity(path: Path, target: str) -> tuple[str, str]:
    portable_member_name(path.name, allow_directory=False)
    if target == "wheel":
        if not path.name.endswith(".whl"):
            raise ValueError("wheel filename is malformed")
        parts = path.name[:-4].split("-")
        if len(parts) not in (5, 6) or any(
            re.fullmatch(r"[A-Za-z0-9_.]+", tag) is None for tag in parts[-3:]
        ):
            raise ValueError("wheel filename identity is malformed")
        if len(parts) == 6 and re.fullmatch(r"[0-9][A-Za-z0-9_]*", parts[2]) is None:
            raise ValueError("wheel build tag is malformed")
        distribution, version = parts[:2]
    else:
        if not path.name.endswith(".tar.gz") or "-" not in path.name[:-7]:
            raise ValueError("sdist filename identity is malformed")
        distribution, version = path.name[:-7].rsplit("-", 1)
    if (
        re.fullmatch(r"[A-Za-z0-9_]+", distribution) is None
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+!]{0,127}", version) is None
    ):
        raise ValueError("archive distribution or version identity is malformed")
    return distribution, version


def _inspect_distribution(
    path: Path, target: str, limits: ArchiveLimits
) -> dict[str, Any]:
    errors = []
    entries = []
    version = None
    try:
        distribution, filename_version = _archive_identity(path, target)
        raw = read_archive_bytes(path, limits)
        opener = validated_zip if target == "wheel" else validated_sdist
        expected_metadata = (
            f"{distribution}-{filename_version}.dist-info/METADATA"
            if target == "wheel"
            else f"{distribution}-{filename_version}/PKG-INFO"
        )
        with opener(raw, limits) as (archive, members):
            names = [
                member.filename if target == "wheel" else member.name
                for member in members
            ]
            if target == "wheel":
                owners = [
                    name
                    for name in names
                    if len(name.split("/")) == 2
                    and name.endswith(".dist-info/METADATA")
                ]
                if owners != [expected_metadata]:
                    raise ValueError(
                        "wheel requires exactly one expected metadata owner"
                    )
            elif expected_metadata not in names or any(
                name.split("/", 1)[0] != f"{distribution}-{filename_version}"
                for name in names
            ):
                raise ValueError(
                    "sdist members require the expected root and metadata owner"
                )
            for member, name in zip(members, names):
                directory = member.is_dir() if target == "wheel" else member.isdir()
                if directory:
                    continue
                size = member.file_size if target == "wheel" else member.size
                limit = (
                    min(limits.max_member_bytes, 1024 * 1024)
                    if name == expected_metadata
                    else limits.max_member_bytes
                )
                if size > limit:
                    raise ValueError(
                        "distribution metadata or member byte budget exceeded"
                    )
                stream = (
                    archive.open(member)
                    if target == "wheel"
                    else archive.extractfile(member)
                )
                if stream is None:
                    raise ValueError("archive member could not be read")
                with stream:
                    data = read_stream_bytes(
                        stream, max_bytes=limit, expected_size=size
                    )
                entries.append(
                    {
                        "path": name,
                        "size_bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
                if name == expected_metadata:
                    message = Parser().parsestr(data.decode("utf-8"), headersonly=True)
                    versions = message.get_all("Version", [])
                    projects = message.get_all("Name", [])
                    if (
                        len(versions) != 1
                        or len(projects) != 1
                        or str(versions[0]).strip() != filename_version
                        or _distribution_name(str(projects[0]).strip())
                        != _distribution_name(distribution)
                    ):
                        raise ValueError(
                            "archive metadata name/version differs from filename identity"
                        )
                    version = filename_version
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        EOFError,
        zipfile.BadZipFile,
        tarfile.TarError,
        zlib.error,
    ) as error:
        errors.append(str(error))
    if version is None and not errors:
        errors.append(f"{target} metadata version is missing")
    return {
        "valid": not errors,
        "version": version,
        "entries": entries,
        "errors": errors,
    }


def inspect_wheel(
    path: Path, *, limits: ArchiveLimits = DEFAULT_LIMITS
) -> dict[str, Any]:
    return _inspect_distribution(path, "wheel", limits)


def inspect_sdist(
    path: Path, *, limits: ArchiveLimits = DEFAULT_LIMITS
) -> dict[str, Any]:
    return _inspect_distribution(path, "sdist", limits)


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
    directory: Path,
    records: list[Mapping[str, object]],
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> dict[str, Any]:
    """Verify an exact bounded file set; format identity is checked by inspection."""
    errors = []
    try:
        if type(records) is not list or not 1 <= len(records) <= 128:
            raise ValueError("artifact records require a bounded nonempty list")
        bounded_json_text(records, max_bytes=1024 * 1024)
        expected = {}
        total = 0
        for record in records:
            if type(record) is not dict or set(record) != {
                "type",
                "filename",
                "sha256",
                "size_bytes",
            }:
                raise ValueError("artifact record fields are malformed")
            filename = record["filename"]
            portable_member_name(filename, allow_directory=False)
            if "/" in filename or record["type"] not in ("wheel", "sdist"):
                raise ValueError("invalid artifact filename or type")
            suffix = ".whl" if record["type"] == "wheel" else ".tar.gz"
            if not filename.endswith(suffix):
                raise ValueError("artifact filename does not match its type")
            identity = member_identity(filename)
            if identity in expected:
                raise ValueError("duplicate artifact filename or portable alias")
            expected[identity] = record
            size, digest = record["size_bytes"], record["sha256"]
            if (
                type(size) is not int
                or not 1 <= size <= limits.max_archive_bytes
                or type(digest) is not str
                or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            ):
                raise ValueError("artifact size or digest is malformed")
            total += size
        if total > limits.max_expanded_bytes:
            raise ValueError("artifact-set aggregate byte budget exceeded")
        from .archive_io import reject_path_links

        reject_path_links(directory)
        root = directory.resolve(strict=True)
        observed = set()
        with os.scandir(root) as entries:
            for number, entry in enumerate(entries):
                if (
                    number >= len(records)
                    or not entry.is_file(follow_symlinks=False)
                    or entry.is_symlink()
                ):
                    raise ValueError(
                        "artifact directory contains an unexpected or unsafe entry"
                    )
                identity = member_identity(entry.name)
                if identity not in expected or identity in observed:
                    raise ValueError(
                        "artifact directory differs from the declared exact file set"
                    )
                observed.add(identity)
        if observed != expected.keys():
            raise ValueError("artifact directory is missing declared files")
        for record in records:
            path = root / record["filename"]
            reject_path_links(path)
            with path.open("rb") as stream:
                data = read_stream_bytes(
                    stream,
                    max_bytes=record["size_bytes"],
                    expected_size=record["size_bytes"],
                )
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                errors.append(
                    "artifact bytes do not match certificate: " + record["filename"]
                )
    except (OSError, KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
    return {
        "valid": not errors,
        "artifact_count": len(records) if type(records) is list else 0,
        "errors": errors,
    }


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
    artifact_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if (
        type(records) is not list
        or len(records) != 2
        or any(type(item) is not dict for item in records)
        or sum(item.get("type") == "wheel" for item in records) != 1
        or sum(item.get("type") == "sdist" for item in records) != 1
    ):
        return {
            "valid": False,
            "source_product_digest": source_product_digest,
            "errors": ["artifact set requires exactly one wheel and one sdist"],
        }
    if source_root is not None and artifact_manifest is not None:
        return {
            "valid": False,
            "source_product_digest": source_product_digest,
            "errors": ["artifact manifest authority is ambiguous"],
        }
    if artifact_manifest is not None:
        intrinsic = validate_artifact_manifest(artifact_manifest)
        if not intrinsic["valid"]:
            return {
                "valid": False,
                "source_product_digest": source_product_digest,
                "errors": intrinsic["errors"],
            }
    verified = verify_artifact_records(directory, records)
    errors = list(verified["errors"])
    if not verified["valid"]:
        return {
            "valid": False,
            "source_product_digest": source_product_digest,
            "errors": errors,
        }
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
    if source_root is not None and artifact_manifest is not None:
        errors.append("artifact manifest authority is ambiguous")
        manifest = None
    elif artifact_manifest is not None:
        manifest = artifact_manifest
    else:
        manifest = (
            generate_artifact_manifest(source_root) if source_root is not None else None
        )
    artifact_checks: dict[str, Any] = {}
    if manifest is not None:
        manifest_check = validate_artifact_manifest(manifest)
        artifact_checks["manifest"] = manifest_check
        errors.extend(manifest_check["errors"])
        if manifest.get("version") != version:
            errors.append(
                "artifact manifest version does not match authoritative version"
            )
        if manifest_check["valid"]:
            wheel_check = verify_built_artifact(
                directory / str(wheel_record["filename"]),
                manifest,
                package_target="wheel",
            )
            sdist_check = verify_built_artifact(
                directory / str(sdist_record["filename"]),
                manifest,
                package_target="sdist",
            )
            projection_check = verify_declared_projection_duplicates(
                manifest, wheel_check["entries"], sdist_check["entries"]
            )
            artifact_checks.update(
                {
                    "wheel": wheel_check,
                    "sdist": sdist_check,
                    "projections": projection_check,
                }
            )
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
