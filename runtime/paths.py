"""Locate framework assets in a source checkout or installed distribution."""

from __future__ import annotations

from pathlib import Path
import sysconfig


SOURCE_ONLY_ROOTS = {"tests", "scripts"}


def framework_root() -> Path:
    source = Path(__file__).resolve().parents[1]
    if (source / "bootstrap" / "startup.toml").is_file():
        return source
    installed = Path(sysconfig.get_path("data")) / "share" / "engineering-bootstrap"
    if (installed / "bootstrap" / "startup.toml").is_file():
        return installed
    raise FileNotFoundError("engineering bootstrap framework assets are not installed")


def is_source_checkout(root: Path) -> bool:
    root = root.resolve()
    return (root / "pyproject.toml").is_file() and (root / "runtime").is_dir()


def resolve_declared_path(root: Path, relative: str | Path) -> Path | None:
    """Resolve a source declaration against source or lean installed layouts.

    Tests and release-build scripts are deliberate sdist-only declarations and
    therefore have no normal runtime-wheel path.
    """
    root = root.resolve()
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"declared framework path must be relative: {relative}")
    if is_source_checkout(root):
        return root / value
    parts = value.parts
    if not parts:
        return root
    package_root = Path(__file__).resolve().parent
    if parts[0] == "runtime":
        return package_root.joinpath(*parts[1:])
    if parts[0] == "builders":
        return package_root.joinpath("builders", *parts[1:])
    if parts[0] in SOURCE_ONLY_ROOTS:
        return None
    return root / value


def declared_file_available(root: Path, relative: str | Path) -> bool:
    resolved = resolve_declared_path(root, relative)
    return resolved is None or resolved.is_file()
