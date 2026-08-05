"""Authoritative package version and immutable Git release identity."""

from __future__ import annotations

import importlib.metadata
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


EXPECTED_REPOSITORY = "Mountain-Nomad-BC/Pacify-X"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def authoritative_version(root: Path) -> str:
    pyproject = root.resolve() / "pyproject.toml"
    if pyproject.is_file():
        value = str(
            tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
        )
    else:
        value = importlib.metadata.version("engineering-loop-bootstrap")
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError("pyproject project.version must be an exact semantic version")
    return value


def validate_version_surfaces(
    root: Path, *, asserted: str | None = None
) -> dict[str, Any]:
    root = root.resolve()
    version = authoritative_version(root)
    errors: list[str] = []
    runtime_text = (root / "runtime/version.py").read_text(encoding="utf-8")
    match = re.search(r'(?m)^VERSION\s*=\s*"([^"]+)"\s*$', runtime_text)
    runtime_version = match.group(1) if match else None
    if runtime_version != version:
        errors.append(
            f"runtime/version.py={runtime_version!r}, pyproject.toml={version!r}"
        )
    readme = (root / "README.md").read_text(encoding="utf-8")
    readme_match = re.search(
        r"(?m)^\*\*Current release:\*\* v([0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)", readme
    )
    readme_version = readme_match.group(1) if readme_match else None
    if readme_version != version:
        errors.append(
            f"README current release={readme_version!r}, pyproject.toml={version!r}"
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
        "errors": errors,
    }


def _git(root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if process.returncode:
        detail = (process.stderr or process.stdout).strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return process.stdout.strip()


def normalize_repository(value: str) -> str:
    text = value.strip().removesuffix(".git")
    if text.startswith("git@github.com:"):
        return text.split(":", 1)[1]
    match = re.fullmatch(r"https?://github\.com/(.+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return text


def capture_git_identity(
    root: Path,
    *,
    version: str | None = None,
    expected_repository: str = EXPECTED_REPOSITORY,
) -> dict[str, Any]:
    root = root.resolve()
    version = version or authoritative_version(root)
    expected_tag = f"v{version}"
    errors: list[str] = []
    try:
        commit = _git(root, "rev-parse", "HEAD")
        tree = _git(root, "rev-parse", "HEAD^{tree}")
        status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
        remote_url = _git(root, "remote", "get-url", "origin")
        repository = normalize_repository(remote_url)
        object_type = _git(root, "cat-file", "-t", f"refs/tags/{expected_tag}")
        tag_commit = _git(root, "rev-list", "-n", "1", expected_tag)
    except ValueError as error:
        return {
            "schema_version": "1.0",
            "valid": False,
            "repository": None,
            "commit_sha": None,
            "tree_sha": None,
            "tag": expected_tag,
            "dirty": True,
            "errors": [str(error)],
        }
    if status:
        errors.append("Git worktree contains tracked or untracked changes")
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
        "dirty": bool(status),
        "errors": errors,
    }


def verify_recorded_git_identity(
    root: Path,
    recorded: dict[str, Any],
    *,
    expected_repository: str = EXPECTED_REPOSITORY,
) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    try:
        repository = normalize_repository(_git(root, "remote", "get-url", "origin"))
        tag = str(recorded.get("tag", ""))
        tag_type = _git(root, "cat-file", "-t", f"refs/tags/{tag}")
        tag_commit = _git(root, "rev-list", "-n", "1", tag)
        commit_type = _git(root, "cat-file", "-t", str(recorded.get("commit_sha", "")))
        tree = _git(root, "rev-parse", f"{recorded.get('commit_sha')}^{{tree}}")
    except ValueError as error:
        return {"valid": False, "errors": [str(error)]}
    if (
        repository.casefold() != expected_repository.casefold()
        or repository.casefold() != str(recorded.get("repository", "")).casefold()
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
