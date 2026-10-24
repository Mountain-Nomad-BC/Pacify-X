"""Compatibility entrypoint; implementation and authority live in the canonical module."""
from pathlib import Path
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts import validate_certification_pipeline as _canonical

if __name__ == "__main__":
    raise SystemExit(_canonical.main())
else:
    # Alias the module, including private helpers and function globals, so
    # compatibility imports cannot acquire a second implementation owner.
    sys.modules[__name__] = _canonical
