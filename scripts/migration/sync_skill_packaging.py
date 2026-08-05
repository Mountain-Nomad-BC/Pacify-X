"""Synchronize the complete commissioned-skill wheel projection.

The generated section is derived from regular files, not a file-extension
allowlist.  Disposable artifacts and symlinks are excluded explicitly.  Each
file is installed beneath the same skill-relative parent so source, wheel, and
installed inventories can be compared exactly.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
START = "# BEGIN GENERATED OPERATIONAL SKILL DATA FILES"
END = "# END GENERATED OPERATIONAL SKILL DATA FILES"
EXISTING_MANUAL_SKILLS = {
    "admit-capability",
    "commission-project",
    "diagnose-python-repair",
    "enforce-governance-controls",
    "orchestrate-engineering-loop",
    "research-to-capability",
    "validate-engineering-outcomes",
    "verify-outcome",
}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}


def _owned_files(skill: Path) -> list[Path]:
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
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix().casefold())


def _generated_lines(root: Path = ROOT) -> list[str]:
    lines = [START]
    skills_root = root / ".agents/skills"
    for skill in sorted(skills_root.iterdir(), key=lambda item: item.name.casefold()):
        if not skill.is_dir() or skill.name in EXISTING_MANUAL_SKILLS:
            continue
        grouped: dict[str, list[Path]] = defaultdict(list)
        for source in _owned_files(skill):
            parent = source.parent.relative_to(skill)
            target = f"share/engineering-bootstrap/.agents/skills/{skill.name}"
            if parent.parts:
                target += "/" + parent.as_posix()
            grouped[target].append(source)
        for target in sorted(grouped, key=str.casefold):
            values = ", ".join(
                f'"{source.relative_to(root).as_posix()}"' for source in grouped[target]
            )
            lines.append(f'"{target}" = [{values}]')
    lines.append(END)
    return lines


def render(current: str, root: Path = ROOT) -> str:
    """Return a complete idempotent projection without mutating the source."""
    prefix = (
        current.split(START, 1)[0].rstrip() if START in current else current.rstrip()
    )
    return prefix + "\n" + "\n".join(_generated_lines(root)) + "\n"


def main() -> None:
    current = PYPROJECT.read_text(encoding="utf-8")
    PYPROJECT.write_text(render(current), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
