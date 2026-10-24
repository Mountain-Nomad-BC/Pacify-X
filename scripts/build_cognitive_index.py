"""Build the deterministic metadata-only cognitive map projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.cognitive_core.index_builder import (
    build_cognitive_index,
    validate_cognitive_index,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--admission-event-id")
    args = parser.parse_args(argv)
    payload = build_cognitive_index(args.root)
    validation = validate_cognitive_index(args.root, payload)
    if not validation["valid"]:
        print(json.dumps(validation, indent=2))
        return 1
    admission = (args.admission_event_id or "").strip()
    if not admission:
        print(json.dumps({
            "valid": False,
            "errors": [
                "cognitive map publication requires an explicit current work admission"
            ],
        }, indent=2))
        return 1
    from runtime.guarded_registry_projection import (
        GuardedProjectionError,
        publish_guarded_registry_projection,
    )

    root = args.root.resolve(strict=True)
    output = args.output
    if output.is_absolute():
        try:
            output = output.resolve().relative_to(root)
        except ValueError:
            print(json.dumps({
                "valid": False,
                "errors": ["cognitive map output must stay inside the project root"],
            }, indent=2))
            return 1
    relative = Path(str(output).replace("\\", "/")).as_posix()
    if not (relative.startswith("registry/") and relative.endswith(".json")):
        print(json.dumps({
            "valid": False,
            "errors": ["cognitive map output must be a registry JSON projection"],
        }, indent=2))
        return 1
    try:
        publication = publish_guarded_registry_projection(
            root, relative, payload, admission_event_id=admission,
        )
    except GuardedProjectionError as error:
        print(json.dumps({"valid": False, "errors": [str(error)]}, indent=2))
        return 1
    print(json.dumps({**validation, "publication": publication}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
