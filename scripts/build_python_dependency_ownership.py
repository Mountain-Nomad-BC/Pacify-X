"""Inventory and classify imports across every packaged Python surface."""

from __future__ import annotations

import argparse
import ast
import io
import json
from pathlib import Path
import sys
import tokenize


LOCAL = {"runtime", "builders", "scripts", "engineering_bootstrap", "tests", "docs"}
TEST_ONLY = {"pytest": "pytest", "yaml": "PyYAML", "jsonschema": "jsonschema"}
DECLARED_REQUIRED = {"yaml": "PyYAML"}
MAX_SOURCE_FILES = 10_000
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_TOKENS = 250_000
MAX_IMPORT_OCCURRENCES = 1_000_000
MAX_IMPORT_ASSOCIATIONS = 100_000


def build(root: Path) -> dict[str, object]:
    from runtime.archive_io import (
        member_identity,
        portable_member_name,
        read_stream_bytes,
        reject_path_links,
    )
    from runtime.json_io import bounded_json_text, load_json_object

    reject_path_links(root)
    root = root.resolve(strict=True)
    inventory = root / "registry/python_surface_ownership.json"
    reject_path_links(inventory)
    ownership = load_json_object(inventory, max_bytes=4 * 1024 * 1024)
    records = ownership.get("records")
    if (
        ownership.get("schema_version") != "1.0"
        or type(records) is not list
        or not 1 <= len(records) <= MAX_SOURCE_FILES
    ):
        raise ValueError(
            "Python surface ownership requires a supported bounded record list"
        )
    planned = []
    seen = set()
    total_bytes = 0
    for record in records:
        if type(record) is not dict or type(record.get("packaged")) is not bool:
            raise ValueError("Python surface packaged designation must be Boolean")
        relative = portable_member_name(record.get("path"), allow_directory=False)
        identity = member_identity(relative)
        if identity in seen:
            raise ValueError("duplicate Python surface path or portable alias")
        seen.add(identity)
        if not record["packaged"]:
            continue
        if any("quarantine" in part.casefold() for part in relative.split("/")[:-1]):
            raise ValueError("quarantine source inputs are excluded")
        path = root / relative
        reject_path_links(path)
        if (
            not path.resolve(strict=True).is_relative_to(root)
            or path.suffix != ".py"
            or not path.is_file()
        ):
            raise ValueError(
                "packaged Python surface must be a contained regular Python file"
            )
        size = path.stat().st_size
        total_bytes += size
        if size > MAX_SOURCE_FILE_BYTES or total_bytes > MAX_SOURCE_BYTES:
            raise ValueError("packaged Python source byte budget exceeded")
        planned.append((relative, path, size))
    modules: dict[str, set[str]] = {}
    remaining = MAX_SOURCE_BYTES
    occurrences = 0
    associations = 0
    for relative, path, size in sorted(planned):
        reject_path_links(path)
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError("packaged Python source escaped root during acquisition")
        with path.open("rb") as stream:
            raw = read_stream_bytes(
                stream,
                max_bytes=min(MAX_SOURCE_FILE_BYTES, remaining),
                expected_size=size,
            )
        remaining -= len(raw)
        text = raw.decode("utf-8")
        try:
            for count, _ in enumerate(
                tokenize.generate_tokens(io.StringIO(text).readline), 1
            ):
                if count > MAX_SOURCE_TOKENS:
                    raise ValueError(
                        "packaged Python token budget exceeded before AST parsing"
                    )
            tree = ast.parse(text, filename=relative)
        except (SyntaxError, tokenize.TokenError, RecursionError) as error:
            raise ValueError(
                "packaged Python source is not parseable: " + relative
            ) from error
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".", 1)[0]]
            for name in names:
                occurrences += 1
                if occurrences > MAX_IMPORT_OCCURRENCES:
                    raise ValueError("packaged import occurrence budget exceeded")
                paths = modules.setdefault(name, set())
                if len(modules) > MAX_SOURCE_FILES:
                    raise ValueError("packaged import module budget exceeded")
                if relative not in paths:
                    associations += 1
                    if associations > MAX_IMPORT_ASSOCIATIONS:
                        raise ValueError("packaged import association budget exceeded")
                    paths.add(relative)
    records = []
    for name, paths in sorted(modules.items()):
        if name in sys.stdlib_module_names:
            classification, distribution = "standard_library", None
        elif name in LOCAL:
            classification, distribution = "local_product", None
        elif name in DECLARED_REQUIRED and any(
            path.startswith("runtime/") for path in paths
        ):
            classification, distribution = "declared_required", DECLARED_REQUIRED[name]
        elif name in TEST_ONLY and all(path.startswith("tests/") for path in paths):
            classification, distribution = "test_only", TEST_ONLY[name]
        else:
            classification, distribution = "unclassified", None
        records.append(
            {
                "module": name,
                "distribution": distribution,
                "classification": classification,
                "paths": sorted(paths),
            }
        )
    result = {
        "schema_version": "1.0",
        "python": {"minimum": "3.11", "maximum_tested": "3.14"},
        "policy": "Every packaged import is standard-library, local-product, declared-required, optional-gated, test-only, or forbidden.",
        "records": records,
    }
    bounded_json_text(result, max_bytes=32 * 1024 * 1024)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = args.root.resolve() / "registry/python_dependency_ownership.json"
    result = build(args.root)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
            raise SystemExit("Python dependency ownership is stale")
    else:
        path.write_text(rendered, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "valid": True,
                "modules": len(result["records"]),
                "check": args.check,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
