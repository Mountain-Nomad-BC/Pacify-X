"""Reconcile active capability contracts to their exact implementation bytes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def reconcile(root: Path, *, check: bool) -> dict[str, object]:
    resolved = root.resolve(strict=True)
    capability_map = json.loads(
        (resolved / "registry/capability_map.json").read_text(encoding="utf-8")
    )
    outputs: dict[Path, bytes] = {}
    stale: list[str] = []
    for item in capability_map.get("active_capabilities", ()):
        if not isinstance(item, dict):
            raise ValueError("active capability entry must be an object")
        contract_relative = str(item.get("contract") or "")
        implementation_relative = str(item.get("implementation") or "")
        contract_path = resolved / contract_relative
        implementation_path = resolved / implementation_relative
        if not contract_path.is_file() or not implementation_path.is_file():
            raise ValueError(f"active capability paths are missing: {item.get('id')}")
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["hash"] = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
        encoded = json.dumps(contract, indent=2, ensure_ascii=False) + "\n"
        payload = encoded.encode("utf-8")
        outputs[contract_path] = payload
        if contract_path.read_bytes() != payload:
            stale.append(contract_relative)
    if not check:
        for path, payload in outputs.items():
            prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
            prepared.write_bytes(payload)
            os.replace(prepared, path)
    return {
        "schema_version": "px.active-capability-hash-reconciliation/1.0",
        "valid": not stale,
        "check": check,
        "active_count": len(outputs),
        "stale": stale,
    }
