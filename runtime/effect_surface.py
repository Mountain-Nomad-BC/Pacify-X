"""Inventory and enforce process, network, archive, and mutation effect surfaces."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


PROCESS_CALLS = {"subprocess.run", "subprocess.Popen", "subprocess.check_output", "subprocess.check_call", "os.system"}
NETWORK_PREFIXES = ("requests.", "urllib.request.", "socket.", "http.client.")
MUTATION_NAMES = {"write_text", "write_bytes", "mkdir", "replace", "rename", "touch", "copy", "copy2", "copytree", "move", "rmtree", "unlink", "rmdir", "extract", "extractall"}
DESTRUCTIVE_NAMES = {"rmtree", "unlink", "rmdir"}


def _call_name(node: ast.Call) -> str:
    value: ast.AST = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _popen_communication_timeout(tree: ast.AST, popen: ast.Call) -> str | None:
    """Return the timeout used to reap a Popen handle in the same function."""
    scope = next(
        (
            item
            for item in ast.walk(tree)
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.lineno <= popen.lineno <= getattr(item, "end_lineno", item.lineno)
        ),
        tree,
    )
    handle = None
    for item in ast.walk(scope):
        if isinstance(item, (ast.Assign, ast.AnnAssign)) and item.value is popen:
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            if len(targets) == 1 and isinstance(targets[0], ast.Name):
                handle = targets[0].id
                break
    if handle is None:
        return None
    for item in ast.walk(scope):
        if not isinstance(item, ast.Call) or not isinstance(item.func, ast.Attribute):
            continue
        if item.func.attr != "communicate" or not isinstance(item.func.value, ast.Name) or item.func.value.id != handle:
            continue
        timeout = next((keyword.value for keyword in item.keywords if keyword.arg == "timeout"), None)
        if timeout is not None:
            return f"communicate(timeout={ast.unparse(timeout)})"
    return None


def discover_effect_surfaces(root: Path) -> list[dict[str, Any]]:
    root = root.resolve()
    records = []
    for path in sorted(root.rglob("*.py"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts or relative.startswith("tests/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call = _call_name(node)
            leaf = call.rsplit(".", 1)[-1]
            if call in PROCESS_CALLS:
                effect = "process"
            elif call.startswith(NETWORK_PREFIXES):
                effect = "network"
            elif leaf in MUTATION_NAMES or call == "os.remove":
                effect = "filesystem_mutation"
            else:
                continue
            keywords = {str(item.arg): ast.unparse(item.value) for item in node.keywords if item.arg}
            process_timeout = keywords.get("timeout")
            if call == "subprocess.Popen":
                process_timeout = _popen_communication_timeout(tree, node)
            semantic = f"{relative}:{node.lineno}:{call}:{ast.dump(node, include_attributes=False)}"
            records.append({
                "id": hashlib.sha256(semantic.encode()).hexdigest()[:20],
                "path": relative,
                "line": node.lineno,
                "call": call,
                "effect": effect,
                "owner": relative.split("/", 1)[0],
                "policy": "policies/contained-execution.json" if effect in {"process", "network"} else "policies/artifact-preservation.json",
                "approval": "required_for_material_or_external_effects",
                "containment": "validated_path_and_bounded_scope",
                "timeout": process_timeout if effect == "process" else None,
                "shell": keywords.get("shell"),
                "destructive": leaf in DESTRUCTIVE_NAMES or call == "os.remove",
            })
    return records


def validate_effect_surfaces(root: Path) -> dict[str, Any]:
    root = root.resolve()
    actual = discover_effect_surfaces(root)
    registry_path = root / "registry/effect_surface_ownership.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    errors = []
    if registry.get("records") != actual or registry.get("record_count") != len(actual):
        errors.append("effect-surface ownership registry is stale")
    for record in actual:
        if not (root / record["policy"]).is_file():
            errors.append(f"{record['id']}: missing effect policy")
        if record["effect"] == "process":
            if record["call"] == "os.system" or record["shell"] == "True":
                errors.append(f"{record['path']}:{record['line']}: unsafe shell execution")
            if record["timeout"] is None:
                errors.append(f"{record['path']}:{record['line']}: process call lacks timeout")
        if record["destructive"]:
            errors.append(f"{record['path']}:{record['line']}: hard-delete surface is prohibited")
    counts: dict[str, int] = {}
    for record in actual:
        counts[record["effect"]] = counts.get(record["effect"], 0) + 1
    return {"schema_version": "1.0", "valid": not errors, "record_count": len(actual), "counts": dict(sorted(counts.items())), "errors": errors, "records": actual}
