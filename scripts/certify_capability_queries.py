"""Execute deterministic golden queries against the compact skill index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.query_certification import certify_queries, load_cases  # noqa: E402 -- local source bootstrap
from runtime.registry import skill_navigation_index  # noqa: E402 -- local source bootstrap


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = args.cases or args.root / "registry" / "golden_capability_queries.json"
    payload = certify_queries(skill_navigation_index(args.root), load_cases(cases))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: payload[key]
                for key in ("complete", "case_count", "passed", "failed")
            }
        )
    )
    raise SystemExit(0 if payload["complete"] else 1)
