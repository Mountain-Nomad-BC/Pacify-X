"""Build the deterministic local specialist-provider graph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.agent_provider import build_agent_graph  # noqa: E402
from runtime.guarded_registry_projection import publish_guarded_registry_projection, GuardedProjectionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--output", type=Path, default=Path("registry/agency_agent_graph.json")
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--admission-event-id")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    relative = output.relative_to(root).as_posix()
    if (not relative.startswith('registry/') or not relative.endswith('.json')
            or any(part in {'', '.', '..'} for part in relative.split('/'))):
        raise GuardedProjectionError('agent graph output must remain a project registry JSON path')
    payload = build_agent_graph(root)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.check:
        valid = output.is_file() and output.read_text(encoding="utf-8") == rendered
    else:
        publish_guarded_registry_projection(root, relative, payload,
            admission_event_id=args.admission_event_id)
        valid = True
    result = {"valid": valid, "output": output.relative_to(root).as_posix()}
    print(json.dumps(result, indent=2))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
