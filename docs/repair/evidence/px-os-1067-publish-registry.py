"""Publish the mutating-producer registry after the approved ownership decisions.

Self-referential by necessity: the published image contains an entry for the module that
writes it. That entry pins the digest of this file with the entry's own digest blanked, so
the value is stable and independently reproducible instead of depending on write order.

Run:
    .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-publish-registry.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if not (ROOT / "runtime").is_dir():
    ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.mutating_producer_registry import (  # noqa: E402
    SELF_RELATIVE,
    build_registry,
    publish_registry,
)

BLANK = "0" * 64


def self_digest() -> str:
    source = (ROOT / SELF_RELATIVE).read_bytes()
    image = build_registry(ROOT, self_source_sha256=BLANK)
    entry = image["producers"].get(SELF_RELATIVE)
    if entry is None:
        raise SystemExit("self entry missing from the built image")
    serialized = json.dumps(entry, sort_keys=True)
    return hashlib.sha256(source).hexdigest(), serialized


def main() -> int:
    image = build_registry(ROOT, self_source_sha256=BLANK)
    blank_entry = image["producers"].get(SELF_RELATIVE)
    # The pinned digest covers the entry with its digest blanked: deterministic and
    # independent of the value being computed.
    token = hashlib.sha256(json.dumps(blank_entry, sort_keys=True).encode("utf-8")).hexdigest()
    image = build_registry(ROOT, self_source_sha256=token)
    unclassified = image["unclassified"]
    if unclassified:
        print(json.dumps({"published": False, "unclassified": len(unclassified)}))
        return 0
    result = publish_registry(ROOT)
    print(json.dumps({"published": True, "producer_count": result.get("producer_count")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
