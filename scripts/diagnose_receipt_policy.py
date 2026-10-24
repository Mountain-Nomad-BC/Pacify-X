"""Re-measure the certification receipt policy failure for WAVE-02.

Read-only. Isolates whether the evidence index can currently evaluate source-tree
receipt currentness, and reports the declared receipt inventory.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from runtime.test_profiles import group_status, section_status

    for name, operation in (("section_status", section_status), ("group_status", group_status)):
        try:
            result = operation(ROOT)
            sections = result.get("sections", [])
            groups = result.get("groups", [])
            print(f"{name}: valid={result.get('valid')}")
            print(f"  required_sections={result.get('required_sections')}")
            print(f"  required_groups={result.get('required_groups')}")
            print(f"  errors={result.get('errors')}")
            print(f"  rows={len(sections) if isinstance(sections, list) else sections}")
        except Exception as error:  # noqa: BLE001 - diagnostic probe
            print(f"{name}: RAISED {type(error).__name__}: {error}")
            import traceback

            traceback.print_exc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())