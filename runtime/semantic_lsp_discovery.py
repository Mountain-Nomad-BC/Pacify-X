"""Language-server discovery without package installation or execution side effects."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class ExecutableCandidate:
    name: str
    path: str
    source: str


def _canonical_executable(value: str, *, search_path: str | None) -> str | None:
    path = Path(value).expanduser()
    if path.is_absolute() and path.is_file():
        return str(path.resolve())
    found = shutil.which(value, path=search_path)
    return str(Path(found).resolve()) if found else None


def discover_executables(
    names: Iterable[str],
    *,
    environment: Mapping[str, str] | None = None,
    override_variable: str | None = None,
) -> tuple[ExecutableCandidate, ...]:
    env = dict(os.environ if environment is None else environment)
    search_path = env.get("PATH")
    result: list[ExecutableCandidate] = []
    seen: set[str] = set()
    if override_variable:
        override = env.get(override_variable)
        if override:
            resolved = _canonical_executable(override, search_path=search_path)
            if resolved:
                result.append(ExecutableCandidate(Path(resolved).name, resolved, f"env:{override_variable}"))
                seen.add(os.path.normcase(resolved))
    for name in names:
        resolved = _canonical_executable(name, search_path=search_path)
        if resolved and os.path.normcase(resolved) not in seen:
            result.append(ExecutableCandidate(name, resolved, "PATH"))
            seen.add(os.path.normcase(resolved))
    return tuple(result)
