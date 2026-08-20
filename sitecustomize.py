"""Prevent audit/runtime imports from mutating the authoritative source tree."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True
