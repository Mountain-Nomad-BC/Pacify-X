"""PX-OS-1067 — grant the six confined producers a repository-root output root.

Why this is not the retired `reports/` grant:

* `reports/` named a directory no producer guaranteed. This root is the repository itself,
  and each of the six producers now *enforces* that its destinations resolve strictly inside
  it (runtime/confined_output.py), publishing atomically and refusing traversal, symlinks and
  the root itself. The guarantee is code, tested in tests/test_confined_output.py.
* Grants are per producer, per write class, pinned to exact source bytes. A drift in any of
  the six voids its grant rather than silently continuing.
* Deletion is never authorized. Retention is run-scoped; a significant reduction requires the
  owner to amend the record.

Run:
    .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-grant-confined-outputs.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if not (ROOT / "runtime").is_dir():
    ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "registry/producer_output_roots.json"

ROOT_KEY = "REPOSITORY_ROOT"
WRITE_CLASS = "caller_directed_report"
PRODUCERS = (
    "scripts/audit_sanitization.py",
    "scripts/build_integration_disposition.py",
    "scripts/cleanup_python_caches.py",
    "scripts/import_adversarial_reaudit.py",
    "scripts/inventory/rehash_inventory_partitions.py",
    "scripts/sanitize_tree.py",
)


def sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


document = json.loads(REGISTRY.read_text(encoding="utf-8"))
document["roots"] = {
    ROOT_KEY: {
        "owner": "repository owner (Ben)",
        "granted_by": "owner decision 2026-11-03",
        "granted_at": "2026-11-03",
        "retention": "run-scoped",
        "invocation_model": "caller-directed CLI argument, confined by the producer must resolve strictly inside the repository root before any write",
        "deletion_authorized": False,
        "confinement_evidence": [
            "runtime/confined_output.py",
            "tests/test_confined_output.py",
        ],
    }
}

existing = {grant["producer"]: grant for grant in document.get("grants") or []}
for producer in PRODUCERS:
    existing[producer] = {
        "producer": producer,
        "root": ROOT_KEY,
        "write_class": WRITE_CLASS,
        "source_sha256": sha(producer),
        "status": "active",
        "granted_by": "owner decision 2026-11-03",
        "granted_at": "2026-11-03",
        "scope": "Every caller-directed destination this producer publishes, confined to the repository root and published atomically.",
        "deletion_authorized": False,
    }
document["grants"] = [existing[key] for key in sorted(existing)]

from runtime.output_roots import validate_registry  # noqa: E402

errors = validate_registry(document)
if errors:
    raise SystemExit("registry invalid: " + "; ".join(errors))
REGISTRY.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")
print(json.dumps({"roots": list(document["roots"]), "grants": len(document["grants"])}))
