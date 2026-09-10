"""Authoritative package version and immutable Git release identity."""

from __future__ import annotations

from bisect import bisect_right
import hashlib
import importlib.metadata
import json
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


from .input_files import contained_file, cooperative_deadline, read_file_image
from .json_io import decode_json_object
from .numeric_inputs import bounded_json_value, bounded_text

# The complete packaging manifest includes generated setuptools data-file tables.
# This is release metadata, distinct from the 64 KiB startup configuration.
MAX_PYPROJECT_BYTES = 1024 * 1024

MAX_GIT_BYTES = 16 * 1024 * 1024
MAX_GIT_PATHS = 250000


def _root(value: Path) -> Path:
    from .input_files import directory_root

    return directory_root(value)


def _image(root: Path, relative: str, limit: int) -> bytes:
    deadline = cooperative_deadline()
    path, info = contained_file(root, relative)
    return bytes(read_file_image(path, info, limit=limit, deadline=deadline))


def _version(value: object) -> str:
    value = bounded_text(value, "release version", maximum=128, strip=False)
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError("package version must be a stable or explicit .dev version")
    return value


def _git_path(value: object) -> str:
    # Git -z records are source identities, not display strings. Whitespace and
    # literal backslashes are never normalized into a different filename.
    if (
        type(value) is not str
        or not value
        or len(value) > 4096
        or len(value.encode("utf-8")) > 4096
    ):
        raise ValueError("Git path must be bounded nonempty UTF-8 text")
    if (
        "\0" in value
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or any(p in {"", ".", ".."} for p in value.split("/"))
    ):
        raise ValueError("Git path must be an exact relative source identity")
    return value


def _git_paths(root: Path, *arguments: str) -> set[str]:
    value = _git(root, *arguments)
    if (
        type(value) is not str
        or len(value) > MAX_GIT_BYTES
        or len(value.encode("utf-8")) > MAX_GIT_BYTES
    ):
        raise ValueError("Git path output exceeds its parsing bound")
    if not value:
        return set()
    if not value.endswith("\0") or value.count("\0") > MAX_GIT_PATHS:
        raise ValueError("Git path output is incomplete or exceeds its record bound")
    return {_git_path(item) for item in value[:-1].split("\0")}


def _mutable_policy(root: Path) -> tuple[dict, str | None]:
    try:
        raw = _image(root, "policies/release-artifact-policy.json", 1024 * 1024)
    except FileNotFoundError:
        return {}, None
    policy = decode_json_object(
        raw, max_bytes=1024 * 1024, max_depth=32, max_nodes=100000
    )
    for field in ("control_output_paths", "control_output_prefixes"):
        values = policy.get(field, [])
        if type(values) is not list or len(values) > 10000:
            raise ValueError("mutable-output policy requires bounded path arrays")
        for value in values:
            bounded_text(value, "mutable-output path", maximum=4096, strip=False)
            if field.endswith("prefixes"):
                if not value.endswith("/"):
                    raise ValueError(
                        "mutable-output prefix must end at a directory boundary"
                    )
                _git_path(value[:-1])
            else:
                _git_path(value)
    return policy, hashlib.sha256(raw).hexdigest()


def _mutable_rules(policy: dict) -> tuple[frozenset[str], tuple[str, ...]]:
    # Remove redundant descendants once. The remaining prefix intervals are
    # disjoint, so one binary-search predecessor answers each path query.
    prefixes = []
    for prefix in sorted(
        {v.casefold() for v in policy.get("control_output_prefixes", [])}
    ):
        if not prefixes or not prefix.startswith(prefixes[-1]):
            prefixes.append(prefix)
    return frozenset(
        v.casefold() for v in policy.get("control_output_paths", [])
    ), tuple(prefixes)


def _mutable_match(
    relative: str, rules: tuple[frozenset[str], tuple[str, ...]]
) -> bool:
    from .repository_scope import is_external_environment_relative

    _git_path(relative)
    # Native path aliases cannot acquire policy authority by normalization.
    if "\\" in relative:
        return False
    if is_external_environment_relative(Path(relative)):
        return True
    folded = relative.casefold()
    index = bisect_right(rules[1], folded) - 1
    return folded in rules[0] or index >= 0 and folded.startswith(rules[1][index])


EXPECTED_REPOSITORY = "Mountain-Nomad-BC/Pacify-X"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:\.dev[0-9]+)?$")


def authoritative_version(root: Path) -> str:
    root = _root(root)
    try:
        raw = _image(root, "pyproject.toml", MAX_PYPROJECT_BYTES)
    except FileNotFoundError:
        return _version(importlib.metadata.version("engineering-loop-bootstrap"))
    try:
        document = tomllib.loads(
            raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        )
    except (ValueError, RecursionError) as error:
        raise ValueError("invalid bounded version metadata TOML") from error
    project = document.get("project")
    if type(project) is not dict:
        raise ValueError("pyproject requires an actual project table")
    return _version(project.get("version"))


def validate_version_surfaces(
    root: Path, *, asserted: str | None = None
) -> dict[str, Any]:
    root = _root(root)
    if asserted is not None:
        asserted = _version(asserted)
    version = authoritative_version(root)
    errors: list[str] = []
    runtime_text = (
        _image(root, "runtime/version.py", 65536)
        .decode("utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    matches = re.findall(r'(?m)^VERSION\s*=\s*"([^"\r\n]+)"[ \t]*$', runtime_text)
    declarations_count = len(re.findall(r"(?m)^VERSION\b", runtime_text))
    runtime_version = (
        matches[0]
        if len(matches) == 1 and declarations_count == 1 and len(matches[0]) <= 128
        else None
    )
    if runtime_version != version:
        errors.append(
            f"runtime/version.py={runtime_version!r}, pyproject.toml={version!r}"
        )
    readme = (
        _image(root, "README.md", 1024 * 1024)
        .decode("utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    declarations = re.findall(r"(?m)^\*\*Current release:\*\*([^\r\n]*)$", readme)
    match = (
        re.match(r"[ \t]+v([^\s]+)(?:[ \t]|$)", declarations[0])
        if len(declarations) == 1
        else None
    )
    readme_version = match.group(1) if match else None
    if readme_version is not None and len(readme_version) > 128:
        readme_version = None
    stable_readme = (
        type(readme_version) is str
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", readme_version) is not None
    )
    development = ".dev" in version
    if not stable_readme or (not development and readme_version != version):
        errors.append(
            f"README signed release={readme_version!r} conflicts with package tree={version!r}"
        )
    if asserted is not None and asserted != version:
        errors.append(f"asserted release={asserted!r}, pyproject.toml={version!r}")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "authoritative_version": version,
        "runtime_version": runtime_version,
        "readme_version": readme_version,
        "asserted_version": asserted,
        "release_channel": "development" if development else "stable",
        "errors": errors,
    }


def _git(root: Path, *arguments: str) -> str:
    if len(arguments) > 32:
        raise ValueError("Git argument count exceeds its bound")
    for argument in arguments:
        bounded_text(argument, "Git argument", maximum=4096, strip=False)
    try:
        # Shared native process ownership and pre-capture bounds remain D252.
        # Binary mode is required here: universal-newline conversion changes
        # NUL-delimited Git path identities containing CR/LF characters.
        process = subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Git identity acquisition failed") from error
    if process.returncode:
        raise ValueError("Git identity command failed")
    if len(process.stdout) > MAX_GIT_BYTES:
        raise ValueError("Git output exceeds its parsing bound")
    try:
        output = process.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Git output is not supported UTF-8") from error
    return output if "-z" in arguments else output.removesuffix("\n").removesuffix("\r")


def normalize_repository(value: str) -> str:
    text = bounded_text(value, "repository identity", maximum=1024).removesuffix(".git")
    if text.startswith("git@github.com:"):
        return text.split(":", 1)[1]
    match = re.fullmatch(r"https?://github\.com/(.+)", text, flags=re.IGNORECASE)
    return match.group(1) if match else text


def _git_changed_paths(root: Path) -> list[str]:
    """Preserve every exact staged, unstaged or non-ignored untracked path."""
    paths: set[str] = set()
    for command in (
        ("diff", "--name-only", "-z", "--no-renames"),
        ("diff", "--cached", "--name-only", "-z", "--no-renames"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        paths.update(_git_paths(root, *command))
        if len(paths) > MAX_GIT_PATHS:
            raise ValueError("combined Git path inventory exceeds its bound")
    return sorted(paths, key=lambda p: (p.casefold(), p))


def _declared_mutable_output(root: Path, relative: str) -> bool:
    """Recognize exact policy-owned mutable paths without normalizing aliases."""
    policy, _ = _mutable_policy(_root(root))
    return _mutable_match(relative, _mutable_rules(policy))


def _release_dirty_state(root: Path) -> dict[str, Any]:
    """Compare Git deltas and the independent canonical product denominator."""
    root = _root(root)
    changed = set(_git_changed_paths(root))
    classifications: dict[str, str] = {}
    classifier_errors: list[str] = []
    policy, policy_sha = _mutable_policy(root)
    if policy_sha is None:
        raise ValueError(
            "release identity requires an independent product classification policy"
        )
    if policy_sha is not None:
        from .release_artifacts import classify_tree

        classified = classify_tree(root)
        records = classified.get("records")
        if type(records) is not list or len(records) > MAX_GIT_PATHS:
            raise ValueError("release classification requires bounded records")
        for item in records:
            if type(item) is not dict:
                raise ValueError("release classification record is malformed")
            path = _git_path(item.get("path"))
            kind = bounded_text(
                item.get("classification"),
                "release classification",
                maximum=128,
                strip=False,
            )
            if path in classifications:
                raise ValueError("release classification contains duplicate paths")
            classifications[path] = kind
        if classified.get("policy_sha256") != policy_sha:
            raise ValueError("release classification policy changed during acquisition")
        if classified.get("valid") is not True:
            classifier_errors = ["canonical release artifact classification is invalid"]
        tracked = _git_paths(root, "ls-files", "--cached", "-z")
        changed.update(
            path
            for path, kind in classifications.items()
            if kind == "product_input" and path not in tracked
        )
        if len(changed) > MAX_GIT_PATHS:
            raise ValueError("release input delta exceeds its path bound")
    rules = _mutable_rules(policy)
    allowed: list[str] = []
    blocking: list[str] = []
    for relative in sorted(changed, key=lambda p: (p.casefold(), p)):
        if classifications.get(relative) in {
            "control_output",
            "evidence_output",
        } or _mutable_match(relative, rules):
            allowed.append(relative)
        else:
            blocking.append(relative)
    return {
        "worktree_dirty": bool(changed),
        "dirty": bool(blocking or classifier_errors),
        "changed_paths": sorted(changed, key=lambda p: (p.casefold(), p)),
        "blocking_paths": blocking,
        "mutable_control_paths": allowed,
        "classifier_errors": classifier_errors,
    }


def capture_git_identity(
    root: Path,
    *,
    version: str | None = None,
    expected_repository: str = EXPECTED_REPOSITORY,
) -> dict[str, Any]:
    expected_tag = None
    errors: list[str] = []
    try:
        root = _root(root)
        version = authoritative_version(root) if version is None else _version(version)
        expected_repository = bounded_text(
            expected_repository, "expected repository", maximum=1024, strip=False
        )
        expected_tag = f"v{version}"
        commit = _git(root, "rev-parse", "HEAD")
        tree = _git(root, "rev-parse", "HEAD^{tree}")
        dirty_state = _release_dirty_state(root)
        remote_url = _git(root, "remote", "get-url", "origin")
        repository = normalize_repository(remote_url)
        object_type = _git(root, "cat-file", "-t", f"refs/tags/{expected_tag}")
        tag_commit = _git(root, "rev-list", "-n", "1", expected_tag)
    except (OSError, ValueError, TypeError, KeyError) as error:
        return {
            "schema_version": "1.0",
            "valid": False,
            "repository": None,
            "commit_sha": None,
            "tree_sha": None,
            "tag": expected_tag,
            "dirty": True,
            "errors": [str(error)[:4096]],
        }
    for value in (commit, tree, tag_commit):
        if (
            type(value) is not str
            or len(value) not in (40, 64)
            or any(c not in "0123456789abcdef" for c in value)
        ):
            errors.append("Git returned a malformed object identity")
    if len(commit) != len(tree) or len(commit) != len(tag_commit):
        errors.append("Git object formats disagree")
    if dirty_state["blocking_paths"]:
        errors.append(
            "Git release inputs contain tracked or untracked changes: "
            + ", ".join(dirty_state["blocking_paths"][:16])
        )
    if dirty_state["classifier_errors"]:
        errors.append(
            "release artifact classification is invalid: "
            + "; ".join(dirty_state["classifier_errors"])
        )
    if repository.casefold() != expected_repository.casefold():
        errors.append(
            f"repository identity {repository!r} does not match {expected_repository!r}"
        )
    if object_type != "tag":
        errors.append(f"{expected_tag} is not an annotated tag")
    if tag_commit != commit:
        errors.append(f"{expected_tag} does not point to HEAD")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "repository": repository,
        "remote_url": remote_url,
        "commit_sha": commit,
        "tree_sha": tree,
        "tag": expected_tag,
        "tag_object_type": object_type,
        "tag_commit_sha": tag_commit,
        "dirty": dirty_state["dirty"],
        "worktree_dirty": dirty_state["worktree_dirty"],
        "dirty_paths": dirty_state["blocking_paths"],
        "mutable_control_paths": dirty_state["mutable_control_paths"],
        "errors": errors,
    }


def _recorded_git_identity(recorded: object) -> dict[str, Any]:
    """Admit exact record data; this does not authenticate its source."""
    if type(recorded) is not dict or len(recorded) > 32:
        raise ValueError("recorded Git identity must be a bounded actual object")
    bounded_json_value(recorded)
    recorded = json.loads(json.dumps(recorded))
    bounded_text(
        recorded.get("repository"), "recorded repository", maximum=1024, strip=False
    )
    tag = bounded_text(recorded.get("tag"), "recorded tag", maximum=129, strip=False)
    if not tag.startswith("v"):
        raise ValueError("recorded tag must name an exact release version")
    _version(tag[1:])
    for field in ("commit_sha", "tree_sha"):
        digest = recorded.get(field)
        if (
            type(digest) is not str
            or len(digest) not in (40, 64)
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError(
                "recorded Git object identity must be an exact hexadecimal object ID"
            )
    if len(recorded["commit_sha"]) != len(recorded["tree_sha"]):
        raise ValueError("recorded Git object formats disagree")
    return recorded


def verify_recorded_git_identity(
    root: Path,
    recorded: dict[str, Any],
    *,
    expected_repository: str = EXPECTED_REPOSITORY,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        root = _root(root)
        expected_repository = bounded_text(
            expected_repository, "expected repository", maximum=1024, strip=False
        )
        recorded = _recorded_git_identity(recorded)
        tag = recorded["tag"]
        repository = normalize_repository(_git(root, "remote", "get-url", "origin"))
        tag_type = _git(root, "cat-file", "-t", f"refs/tags/{tag}")
        tag_commit = _git(root, "rev-list", "-n", "1", tag)
        commit_type = _git(root, "cat-file", "-t", recorded["commit_sha"])
        tree = _git(root, "rev-parse", f"{recorded.get('commit_sha')}^{{tree}}")
    except (OSError, ValueError, TypeError, KeyError) as error:
        return {"valid": False, "errors": [str(error)[:4096]]}
    if (
        repository.casefold() != expected_repository.casefold()
        or repository.casefold() != recorded["repository"].casefold()
    ):
        errors.append("recorded repository identity does not match Git origin")
    if tag_type != "tag":
        errors.append("recorded release tag is not annotated")
    if commit_type != "commit" or tag_commit != recorded.get("commit_sha"):
        errors.append("recorded release tag does not resolve to the certified commit")
    if tree != recorded.get("tree_sha"):
        errors.append("recorded Git tree does not match the certified commit")
    return {
        "valid": not errors,
        "repository": repository,
        "tag_commit_sha": tag_commit,
        "tree_sha": tree,
        "errors": errors,
    }
