"""Locate framework assets in a source checkout or installed distribution."""
from __future__ import annotations

from pathlib import Path
import sysconfig


def framework_root() -> Path:
    source = Path(__file__).resolve().parents[1]
    if (source / "bootstrap" / "startup.toml").is_file():
        return source
    installed = Path(sysconfig.get_path("data")) / "share" / "engineering-bootstrap"
    if (installed / "bootstrap" / "startup.toml").is_file():
        return installed
    raise FileNotFoundError("engineering bootstrap framework assets are not installed")
