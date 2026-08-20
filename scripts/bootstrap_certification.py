"""Parameterized, read-only certification environment bootstrap check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from runtime.certification_readiness import assess_certification_readiness  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Classify PX extension certification prerequisites"
    )
    result.add_argument("--engine-root", type=Path, required=True)
    result.add_argument("--extension-root", type=Path, required=True)
    result.add_argument("--python")
    result.add_argument("--node")
    result.add_argument("--npm")
    result.add_argument("--browser")
    result.add_argument("--vscode")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    result = assess_certification_readiness(
        arguments.engine_root,
        arguments.extension_root,
        python=arguments.python,
        node=arguments.node,
        npm=arguments.npm,
        browser=arguments.browser,
        vscode=arguments.vscode,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
