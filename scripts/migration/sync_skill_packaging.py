"""Synchronize the complete commissioned-skill wheel projection.

The generated section is derived from regular files, not a file-extension
allowlist.  Disposable artifacts and symlinks are excluded explicitly.  Each
file is installed beneath the same skill-relative parent so source, wheel, and
installed inventories can be compared exactly.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Mapping
import tomllib
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
START = "# BEGIN GENERATED OPERATIONAL SKILL DATA FILES"
END = "# END GENERATED OPERATIONAL SKILL DATA FILES"
EXISTING_MANUAL_SKILLS: set[str] = set()
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}


def _owned_files(skill: Path, root: Path = ROOT) -> list[Path]:
    """Return the complete deterministic regular-file inventory for a skill."""
    files = []
    for item in skill.rglob("*"):
        relative = item.relative_to(skill)
        if (
            not item.is_file()
            or item.is_symlink()
            or EXCLUDED_PARTS.intersection(relative.parts)
            or item.suffix.casefold() in EXCLUDED_SUFFIXES
        ):
            continue
        files.append(item)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix().casefold())


def _generated_lines(
    root: Path = ROOT,
    *,
    skill_overlays: Mapping[str, Path] | None = None,
) -> list[str]:
    """Render logical canonical paths from canonical or staged skill trees.

    ``skill_overlays`` lets the lifecycle transaction calculate the exact
    packaging after-image before publishing a canonical directory.  Overlay
    bytes are read from the staged tree, while emitted source paths remain the
    future canonical ``.px/skills/<id>`` paths.
    """
    lines = [START, '"share/engineering-bootstrap/.px" = [".px/skill-index.json"]']
    skills_root = root / ".px/skills"
    overlays = dict(skill_overlays or {})
    canonical = {
        skill.name: skill
        for skill in skills_root.iterdir()
        if skill.is_dir() and not skill.is_symlink()
    }
    canonical.update(overlays)
    for skill_name in sorted(canonical, key=str.casefold):
        skill = canonical[skill_name]
        if not skill.is_dir() or skill.is_symlink() or skill_name in EXISTING_MANUAL_SKILLS:
            continue
        grouped: dict[str, list[Path]] = defaultdict(list)
        for source in _owned_files(skill, root):
            parent = source.parent.relative_to(skill)
            target = f"share/engineering-bootstrap/.px/skills/{skill_name}"
            if parent.parts:
                target += "/" + parent.as_posix()
            grouped[target].append(source)
        for target in sorted(grouped, key=str.casefold):
            values = ", ".join(
                f'".px/skills/{skill_name}/{source.relative_to(skill).as_posix()}"'
                for source in grouped[target]
            )
            lines.append(f'"{target}" = [{values}]')
    facades_root = root / ".agents" / "skills"
    facades = facades_root.iterdir() if facades_root.is_dir() else ()
    for facade in sorted(facades, key=lambda item: item.name.casefold()):
        if not facade.is_dir():
            continue
        grouped: dict[str, list[Path]] = defaultdict(list)
        for source in _owned_files(facade, root):
            parent = source.parent.relative_to(facade)
            target = f"share/engineering-bootstrap/.agents/skills/{facade.name}"
            if parent.parts:
                target += "/" + parent.as_posix()
            grouped[target].append(source)
        for target in sorted(grouped, key=str.casefold):
            values = ", ".join(f'"{source.relative_to(root).as_posix()}"' for source in grouped[target])
            lines.append(f'"{target}" = [{values}]')
    lines.append(END)
    destinations = [line.split('" = ', 1)[0] for line in lines if line.startswith('"')]
    if len(destinations) != len(set(destinations)):
        raise ValueError("generated skill projection contains duplicate destinations")
    return lines


def render(
    current: str,
    root: Path = ROOT,
    *,
    skill_overlays: Mapping[str, Path] | None = None,
) -> str:
    """Return a complete idempotent projection without mutating the source."""
    raw_prefix = current.split(START, 1)[0] if START in current else current
    prefix = "\n".join(
        line for line in raw_prefix.rstrip().splitlines()
        if not line.startswith('"share/engineering-bootstrap/.px/skills/')
        and not line.startswith('"share/engineering-bootstrap/.agents/skills/')
        and not line.startswith('"share/engineering-bootstrap/.px" =')
    ).rstrip()
    return prefix + "\n" + "\n".join(
        _generated_lines(root, skill_overlays=skill_overlays)
    ) + "\n"


def main() -> None:
    current = PYPROJECT.read_text(encoding="utf-8")
    rendered = render(current)
    tomllib.loads(rendered)
    prepared = PYPROJECT.with_name(f".{PYPROJECT.name}.{uuid4().hex}.prepared")
    prepared.write_text(rendered, encoding="utf-8", newline="\n")
    prepared.replace(PYPROJECT)


if __name__ == "__main__":
    main()
