"""Shared repository-copy boundaries for mutation fixtures."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Callable

from runtime.repository_scope import is_external_environment_relative


def canonical_copy_ignore(
    source: Path, *generated_patterns: str
) -> Callable[[str, list[str]], set[str]]:
    """Build a copytree ignore callback that prunes custody before traversal."""
    resolved_source = source.resolve()
    generated = shutil.ignore_patterns(*generated_patterns)

    def ignore(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).resolve().relative_to(resolved_source)
        ignored = set(generated(directory, names))
        ignored.update(
            name
            for name in names
            if name.casefold().endswith(".lock")
            or is_external_environment_relative(relative / name)
        )
        return ignored

    return ignore
