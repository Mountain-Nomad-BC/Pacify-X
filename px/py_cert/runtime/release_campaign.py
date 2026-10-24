"""Compatibility entrypoint; implementation and authority live in the canonical module."""
from pathlib import Path
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from runtime import release_campaign as _canonical

sys.modules[__name__] = _canonical
