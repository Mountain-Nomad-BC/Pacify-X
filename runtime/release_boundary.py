"""Canonical clean-product materialization shared by preflight and finalization."""

from __future__ import annotations

from pathlib import Path
import shutil

from .repository_scope import is_external_environment_relative


def copy_clean_product(source: Path, destination: Path) -> None:
    """Materialize the exact clean product boundary used by finalization."""
    source = source.resolve()
    generated = shutil.ignore_patterns(
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "*.pyc",
        "*.pyo",
        "*.egg-info",
        "build",
        "dist",
        "evidence",
        "release.lock",
        "release-transaction.json",
    )

    def ignore(directory: str, names: list[str]) -> set[str]:
        relative_directory = Path(directory).resolve().relative_to(source)
        ignored = set(generated(directory, names))
        for name in names:
            if is_external_environment_relative(relative_directory / name):
                ignored.add(name)
        return ignored

    shutil.copytree(source, destination, ignore=ignore)
