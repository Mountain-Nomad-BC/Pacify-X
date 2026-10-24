"""Measure the structural reality of extension/server/index.js for PX-GAP-0006.

Read-only. Reports whether the bundle retains recoverable module boundaries
(esbuild factory markers) or whether the pre-bundle sources must be located
elsewhere.
"""

from __future__ import annotations

import pathlib
import re

TARGET = pathlib.Path("extension/server/index.js")

MARKERS = {
    "__commonJS(": "CommonJS module factory",
    "miniCssF(": "CSS module factory",
    "__esm(": "ESM wrapper factory",
    "__toESM(": "ESM interop",
    "__export(": "export helper",
    "__require(": "require helper",
    "__copyProps(": "property copy helper",
    "__defProp(": "property define helper",
}


def main() -> int:
    text = TARGET.read_text(encoding="utf-8", errors="replace")
    print(f"path: {TARGET.as_posix()}")
    print(f"bytes: {len(text.encode('utf-8'))}")
    print(f"lines: {len(text.splitlines())}")
    print()
    print("bundle factory markers:")
    for marker, label in MARKERS.items():
        print(f"  {label:28s} {marker:14s} {len(re.findall(re.escape(marker), text))}")
    print()
    print("provenance markers:")
    for label, pattern in (
        ("sourceMappingURL", r"sourceMappingURL"),
        ("//# sourceMappingURL comment", r"//#\s*sourceMappingURL"),
        ("sourceURL", r"sourceURL="),
        ("webpack", r"webpack"),
        ("esbuild banner", r"esbuild"),
    ):
        print(f"  {label:32s} {len(re.findall(pattern, text))}")
    print()
    candidates = sorted(
        p.as_posix()
        for p in pathlib.Path("extension").rglob("*.map")
    )
    print(f"sourcemap files under extension/: {len(candidates)}")
    for item in candidates[:10]:
        print(f"  {item}")
    build_files = sorted(
        p.as_posix()
        for pattern in ("build*.js", "esbuild*.js", "*.mjs", "*.ts")
        for p in pathlib.Path("extension").rglob(pattern)
        if "node_modules" not in p.as_posix()
    )
    print()
    print("possible pre-bundle sources / build config:")
    for item in build_files[:25]:
        print(f"  {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())