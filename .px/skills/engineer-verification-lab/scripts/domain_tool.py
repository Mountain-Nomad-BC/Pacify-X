#!/usr/bin/env python3
"""Bounded CLI for a projected declared-domain helper; import has no effects."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
import time


def _original_links(path: Path) -> None:
    value = str(path)
    if len(value) > 4096 or len(value.encode("utf-8")) > 4096:
        raise ValueError("wrapper source path exceeds its byte budget")
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError("linked wrapper source path refused")


def _source_root() -> Path:
    original = Path(__file__).absolute()
    _original_links(original)
    if (
        original.name != "domain_tool.py"
        or len(original.parents) < 5
        or original.parent.name != "scripts"
        or original.parents[2].name != "skills"
        or original.parents[3].name != ".px"
    ):
        raise ValueError("source fallback requires the projected domain-wrapper layout")
    root = original.parents[4]
    for relative in (
        "runtime",
        "runtime/__init__.py",
        "runtime/declared_suite.py",
        "runtime/paths.py",
        "runtime/input_files.py",
        "runtime/json_io.py",
        "runtime/numeric_inputs.py",
        "bootstrap/startup.toml",
    ):
        _original_links(root / relative)
        if not (root / relative).exists():
            raise ValueError("projected wrapper source root is incomplete")
    return root


def _runtime():
    namespace = "engineering_bootstrap"
    source_root = None
    try:
        declared = importlib.import_module(namespace + ".declared_suite")
    except ModuleNotFoundError as error:
        if error.name != namespace:
            raise
        source_root = _source_root()
        sys.path.insert(0, str(source_root))
        namespace = "runtime"
        declared = importlib.import_module(namespace + ".declared_suite")
    modules = [declared] + [
        importlib.import_module(namespace + "." + name)
        for name in ("paths", "input_files", "json_io", "numeric_inputs")
    ]
    if source_root is not None:
        expected = (source_root / "runtime").resolve(strict=True)
        for module in modules:
            origin = getattr(module, "__file__", None)
            if not origin or not Path(origin).resolve(strict=True).is_relative_to(
                expected
            ):
                raise ValueError(
                    "cached runtime module differs from projected source root"
                )
    return modules


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("outcome")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    deadline = time.monotonic() + 60.0
    try:
        declared, paths, inputs, codec, numeric = _runtime()
        numeric.bounded_text(args.outcome, "outcome", maximum=512, strip=False)
        numeric.bounded_text(str(args.input), "input path", maximum=4096, strip=False)
        inputs.check_deadline(deadline)
        original = args.input.absolute()
        path, info = inputs.contained_file(original.parent, original.name)
        raw = inputs.read_file_image(
            path, info, limit=8 * 1024 * 1024, deadline=deadline
        )
        payload = codec.decode_json_object(
            raw, max_bytes=8 * 1024 * 1024, max_depth=32, max_nodes=100000
        )
        inputs.check_deadline(deadline)
        result = declared.run_script_outcome(
            paths.framework_root(), args.outcome, payload
        )
        # These cooperative checks cannot interrupt imports, OS calls or the
        # synchronous runtime operation; the invoking process owner bounds those.
        inputs.check_deadline(deadline)
        if type(result) is not dict or type(result.get("valid")) is not bool:
            raise ValueError(
                "runtime result requires an object and actual boolean validity"
            )
        rendered = codec.bounded_json_text(result, max_bytes=8 * 1024 * 1024)
        inputs.check_deadline(deadline)
        print(rendered)
        return 0 if result["valid"] else 1
    except (OSError, ValueError, ImportError) as error:
        print(
            json.dumps(
                {
                    "valid": False,
                    "errors": [type(error).__name__ + ": " + str(error)[:512]],
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
