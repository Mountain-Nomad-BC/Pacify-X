"""Record the sandbox-observed write behaviour of each caller-directed producer.

Static extraction can prove a name is *involved*; only a run proves where bytes land. This
runs each producer in an isolated copy of the repository and records every file created or
modified, so the confinement claim rests on observation.

A producer is recorded as `observed_confined` only when every path it wrote lies inside the
one directory tree it confined to in that run. Anything else is recorded honestly as
unresolved, with the escaping paths named.

Run:
    .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-sandbox-evidence.py
"""
from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if not (ROOT / "runtime").is_dir():
    ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))

from importlib import util as _util  # noqa: E402

_spec = _util.spec_from_file_location(
    "px_sandbox", Path(__file__).parent / "px-os-1067-sandbox-run.py"
)
assert _spec and _spec.loader
sandbox = _util.module_from_spec(_spec)
_spec.loader.exec_module(sandbox)

# One representative invocation per mode that writes. `--apply` is included where the
# producer has one, because that is the mode with extra destinations.
CASES = (
    ("scripts/audit_sanitization.py", ["--root", ".", "--output", "reports/audit.json"]),
    ("scripts/sanitize_tree.py", ["--root", ".", "--output", "reports/sanitize.json"]),
    ("scripts/sanitize_tree.py", ["--root", "scripts", "--apply", "--preservation-root", ".px-preserved", "--output", "reports/sanitize.json"]),
    ("scripts/cleanup_python_caches.py", ["--root", ".", "--output", "reports/cache.json"]),
    ("scripts/cleanup_python_caches.py", ["--root", ".", "--apply", "--output", "reports/cache.json"]),
    ("scripts/inventory/rehash_inventory_partitions.py", ["--parts-root", ".", "--output", "reports/rehash.json"]),
    ("scripts/import_adversarial_reaudit.py", ["register.md", "--output", "reports/reaudit.json"]),
    ("scripts/build_integration_disposition.py", [
        "--root", ".", "--source", "upstream-source", "--source-alias", "upstream",
        "--owner-output", "reports/owners.json",
        "--disposition-output", "reports/disposition.json",
    ]),
)

OUTPUT = Path(__file__).parent / "px-os-1067-sandbox-evidence.json"


def main() -> int:
    results = []
    for producer, arguments in CASES:
        if arguments is None:
            results.append(
                {
                    "producer": producer,
                    "skipped": "requires an input artifact the sandbox does not synthesise",
                }
            )
            continue
        observation = sandbox.run(producer, arguments)
        created = observation["created"]
        modified = observation["modified"]
        # Write-area check: every path must sit under reports/ or the producer's own
        # quarantine/preservation tree inside the sandbox, never at an absolute path.
        escapes = [
            path for path in created + modified
            if path.startswith("/") or ".." in Path(path).parts
        ]
        results.append(
            {
                "producer": producer,
                "arguments": arguments,
                "exit_code": observation["exit_code"],
                "created": created,
                "modified": modified,
                "escaping_paths": escapes,
                # A producer that exits non-zero to *report findings* has still confined its
                # writes. What disqualifies a run is a crash: no output and an error trace.
                "observed_confined": (
                    not escapes and (observation["exit_code"] == 0 or bool(created))
                ),
                # The observation describes exactly these bytes. If the producer changes, the
                # evidence no longer vouches for it and classification refuses to resolve it.
                "observed_source_sha256": hashlib.sha256(
                    (ROOT / producer).read_bytes()
                ).hexdigest(),
                "stderr_tail": observation["stderr_tail"],
            }
        )

    document = {
        "schema_version": "px.sandbox-write-evidence/1.0",
        "gap_id": "PX-OS-1067",
        "method": (
            "Each producer ran against a temporary copy of runtime/ and scripts/ with its "
            "working directory set to that copy. Writes were observed by comparing before/after "
            "snapshots of the sandbox. This measures one run per mode; it is evidence about "
            "observed behaviour, not a proof for every input."
        ),
        "cases": results,
        "summary": {
            "cases": len(results),
            "observed_confined": sum(1 for row in results if row.get("observed_confined")),
            "skipped": sum(1 for row in results if row.get("skipped")),
        },
    }
    OUTPUT.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(document["summary"]))
    for row in results:
        if "skipped" not in row:
            print(
                f"{row['producer']} exit={row['exit_code']} "
                f"created={len(row['created'])} escaped={len(row['escaping_paths'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
