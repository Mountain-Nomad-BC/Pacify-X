from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.release_preflight import generated_dependency_graph


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    policy = json.loads(
        (root / "policies/release-preflight.json").read_text(encoding="utf-8")
    )
    result = generated_dependency_graph(policy["generated_authorities"])
    target = root / "registry/generated_dependency_graph.json"
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
            raise SystemExit("generated dependency graph is stale")
    else:
        target.write_text(rendered, encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
