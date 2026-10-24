"""Report which declared packaged evidence files actually exist.

Read-only. Separates the packaged product-artifact root from the missing
installed-artifact root so the custody state is stated precisely.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    test = (ROOT / "tests" / "test_release_artifacts.py").read_text(encoding="utf-8")
    block = re.search(
        r"DECLARED_PACKAGED_EVIDENCE = \((.*?)\)", test, re.S
    )
    if block is None:
        print("DECLARED_PACKAGED_EVIDENCE not found")
        return 1
    paths = re.findall(r'"(evidence/[^"]+)"', block.group(1))
    print(f"declared packaged evidence: {len(paths)}")
    present = absent = 0
    for relative in paths:
        exists = (ROOT / relative).is_file()
        print(f"  {'EXISTS' if exists else 'ABSENT'}  {relative}")
        present += exists
        absent += not exists
    print(f"present={present} absent={absent}")

    print()
    root = ROOT / "evidence"
    print(f"evidence/ directory exists: {root.is_dir()}")
    print(f"extension/evidence/ exists: {(ROOT / 'extension' / 'evidence').is_dir()}")
    test_evidence = ROOT / ".agentic_engineering_os_px" / "test-evidence"
    if test_evidence.is_dir():
        count = sum(1 for item in test_evidence.rglob("*") if item.is_file())
        print(f".agentic_engineering_os_px/test-evidence/ files: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())