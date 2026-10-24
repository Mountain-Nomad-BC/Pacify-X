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
        # Receipt inclusion is fixture custody, not authored-source classification.
        retained = tuple(Path(namespace) / "test-evidence" / "sections"
                         for namespace in (".agentic_engineering_os_px", ".engineering-bootstrap"))
        def retained_receipt_path(candidate):
            return any(candidate == target or candidate in target.parents
                       or target in candidate.parents for target in retained)
        ignored.update(name for name in names
                       if not retained_receipt_path(relative / name)
                       and is_external_environment_relative(relative / name))
        return ignored

    return ignore
