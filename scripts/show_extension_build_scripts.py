"""Print the extension build/package scripts (avoids shell quoting hazards)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    data = json.loads((ROOT / "extension/package.json").read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    for name in ("build", "build:mcp", "package", "test:vscode-host", "check"):
        print(f"{name}:\n  {scripts.get(name)}\n")
    print(f"main: {data.get('main')}")
    print("files:")
    for item in data.get("files", []):
        print(f"  {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())