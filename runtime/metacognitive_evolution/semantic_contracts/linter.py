from __future__ import annotations
from typing import Any

REQUIRED = {
    "capability_id": str,
    "reads": list,
    "writes": list,
    "epistemic_effects": list,
    "evidence_required": list,
    "rollback": dict,
}

SENSITIVE_PREFIXES = (
    "memory.", "registry.", "permissions.", "external.", "runtime.",
    "filesystem.", "network.", "secrets.", "model."
)

def lint(contract: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    for name, expected in REQUIRED.items():
        if name not in contract:
            errors.append(f"missing required field: {name}")
        elif not isinstance(contract[name], expected):
            errors.append(f"{name} must be {expected.__name__}")

    reads = set(contract.get("reads", [])) if isinstance(contract.get("reads"), list) else set()
    writes = set(contract.get("writes", [])) if isinstance(contract.get("writes"), list) else set()
    prohibited = set(contract.get("prohibited_effects", [])) if isinstance(contract.get("prohibited_effects"), list) else set()
    evidence = contract.get("evidence_required", []) if isinstance(contract.get("evidence_required"), list) else []
    rollback = contract.get("rollback", {}) if isinstance(contract.get("rollback"), dict) else {}

    overlap = writes & prohibited
    if overlap:
        errors.append("declared writes conflict with prohibited effects: " + ", ".join(sorted(overlap)))
    undeclared_sensitive = [
        effect for effect in contract.get("observed_effects", [])
        if effect.startswith(SENSITIVE_PREFIXES) and effect not in writes
    ]
    if undeclared_sensitive:
        errors.append("observed sensitive effects were not declared: " + ", ".join(sorted(undeclared_sensitive)))
    if writes and not rollback.get("required", False):
        warnings.append("writes are declared but rollback.required is false")
    if writes and not rollback.get("method"):
        errors.append("writes require a concrete rollback.method")
    if contract.get("external_effects") and not evidence:
        warnings.append("external effects declared without evidence requirements")
    if not contract.get("epistemic_effects"):
        warnings.append("no epistemic effects declared")
    if reads & writes:
        warnings.append("same resources appear in reads and writes; verify mutation intent")
    return {
        "capability_id": contract.get("capability_id"),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "declared_read_count": len(reads),
        "declared_write_count": len(writes),
    }
