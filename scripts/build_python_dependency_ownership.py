"""Inventory and classify imports across every packaged Python surface."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys


LOCAL = {"runtime", "builders", "scripts", "engineering_bootstrap"}
TEST_ONLY = {"pytest": "pytest", "yaml": "PyYAML"}


def build(root: Path) -> dict[str, object]:
    root = root.resolve()
    ownership = json.loads((root / "registry/python_surface_ownership.json").read_text(encoding="utf-8"))
    modules: dict[str, set[str]] = {}
    for record in ownership["records"]:
        if not record.get("packaged"):
            continue
        relative = str(record["path"])
        tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".", 1)[0]]
            for name in names:
                modules.setdefault(name, set()).add(relative)
    records = []
    for name, paths in sorted(modules.items()):
        if name in sys.stdlib_module_names:
            classification, distribution = "standard_library", None
        elif name in LOCAL:
            classification, distribution = "local_product", None
        elif name in TEST_ONLY and all(path.startswith("tests/") for path in paths):
            classification, distribution = "test_only", TEST_ONLY[name]
        else:
            classification, distribution = "unclassified", None
        records.append({"module": name, "distribution": distribution, "classification": classification, "paths": sorted(paths)})
    return {
        "schema_version": "1.0",
        "python": {"minimum": "3.11", "maximum_tested": "3.14"},
        "policy": "Every packaged import is standard-library, local-product, declared-required, optional-gated, test-only, or forbidden.",
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = args.root.resolve() / "registry/python_dependency_ownership.json"
    rendered = json.dumps(build(args.root), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
            raise SystemExit("Python dependency ownership is stale")
    else:
        path.write_text(rendered, encoding="utf-8", newline="\n")
    print(json.dumps({"valid": True, "modules": len(build(args.root)["records"]), "check": args.check}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
