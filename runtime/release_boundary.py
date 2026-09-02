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
        ".test-orchestration.lock",
        "*.egg-info",
        "build",
        "dist",
        "evidence",
        "release-transaction.json",
    )

    def ignore(directory: str, names: list[str]) -> set[str]:
        relative_directory = Path(directory).resolve().relative_to(source)
        ignored = set(generated(directory, names))
        for name in names:
            relative = relative_directory / name
            # The finalizer holds this mutable control file while it freezes the
            # product.  Copying the locked byte fails on Windows, and the release
            # policy already excludes the file from product identity.
            if relative.as_posix().casefold() == ".engineering-bootstrap/release.lock":
                ignored.add(name)
            elif is_external_environment_relative(relative):
                ignored.add(name)
        return ignored

    shutil.copytree(source, destination, ignore=ignore)
