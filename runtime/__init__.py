"""Bounded, model-agnostic runtime primitives."""

from __future__ import annotations

import sys as _sys


# ``python -m runtime.cli`` imports this package before the CLI module. Setting
# the interpreter guard here prevents the package import and every governed
# child import from writing bytecode into the authoritative source tree.
_sys.dont_write_bytecode = True
