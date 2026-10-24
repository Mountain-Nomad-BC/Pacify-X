"""Inventory and enforce process, network, archive, and mutation effect surfaces."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from .bounded_walk import WalkLimits, bounded_walk
from .repository_scope import is_external_environment_relative


PROCESS_CALLS = {
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.check_output",
    "subprocess.check_call",
    "os.system",
}
NETWORK_PREFIXES = ("requests.", "urllib.request.", "socket.", "http.client.")
MUTATION_NAMES = {
    "write_text",
    "write_bytes",
    "mkdir",
    "replace",
    "rename",
    "link",
    "symlink",
    "hardlink_to",
    "symlink_to",
    "touch",
    "copy",
    "copy2",
    "copytree",
    "move",
    "rmtree",
    "unlink",
    "rmdir",
    "extract",
    "extractall",
}
DESTRUCTIVE_NAMES = {"rmtree", "unlink", "rmdir"}
RESOURCE_LIFECYCLE_OWNER = "runtime/resource_lifecycle.py"
RECOVERABLE_RECLAMATION_OWNERS = {
    "runtime/evidence_custody.py": "policies/operational-evidence-retention.json",
    "scripts/archive_committed_wal.py": "policies/operational-evidence-retention.json",
    "scripts/archive_project_map_history.py": "policies/operational-evidence-retention.json",
    "scripts/run_installed_operational_owner.py": "policies/operational-evidence-retention.json",
    "scripts/run_release_stage_owner.py": "policies/operational-evidence-retention.json",
    "scripts/verify_release_publication.py": "policies/operational-evidence-retention.json",
    # Atomic-write owners remove only the ephemeral temp/probe/stage path they created
    # in the same scope (os.replace publishes it, or the write is rolled back).
    "runtime/semantic_code_transaction.py": "policies/artifact-preservation.json",
    "runtime/semantic_lsp_transaction.py": "policies/artifact-preservation.json",
    # Rollback compensation removes only the prepared replacement path the
    # transaction itself created; the original is restored, never hard-deleted.
    "runtime/semantic_remap_transaction.py": "policies/artifact-preservation.json",
    # The seal writer removes only its own prepared temp path (os.replace publishes
    # the final image, or the write is rolled back).
    "runtime/workspace_manager.py": "policies/artifact-preservation.json",
    "scripts/benchmark_local_models.py": "policies/artifact-preservation.json",
    "scripts/benchmark_model_routes.py": "policies/artifact-preservation.json",
    "scripts/certify_local_model_profiles.py": "policies/artifact-preservation.json",
    "scripts/build_release_successor_configs.py": "policies/artifact-preservation.json",
    # docs architecture: retired generated per-record projections are removed on rebuild;
    # their canonical data now lives in structured Atlas outputs.
    "docs/architecture/tools/build_atlas.py": "policies/artifact-preservation.json",
    # Certification control-plane dual-surface counterparts (px/py_cert mirrors the same
    # owned-ephemeral behaviour as their scripts/ originals above).
    "px/py_cert/scripts/build_release_successor_configs.py": "policies/artifact-preservation.json",
    "px/py_cert/scripts/run_installed_operational_owner.py": "policies/operational-evidence-retention.json",
    "px/py_cert/scripts/run_release_stage_owner.py": "policies/operational-evidence-retention.json",
    "runtime/global_skill_isolation.py": "policies/operational-evidence-retention.json",
    # The gate authority publisher creates one random, exclusive prepared file
    # beside the authority key, hard-links the complete image into place, and
    # removes only that exact unpublished prepared path in its finally block.
    "runtime/gate_runner.py": "policies/operational-evidence-retention.json",
    "runtime/operational_gap_ledger.py": "policies/operational-evidence-retention.json",
    "runtime/skill_studio.py": "policies/operational-evidence-retention.json",
    "runtime/studio_authority.py": "policies/operational-evidence-retention.json",
    "runtime/studio_models.py": "policies/operational-evidence-retention.json",
    "runtime/work_admission.py": "policies/operational-evidence-retention.json",
}
OWNED_PROCESS_SUPERVISORS = {
    "docs/architecture/tools/verify_obsidian_native.py": (
        "bounded_finally_termination_and_wait_with_platform_tree_kill"
    ),
    "scripts/run_installed_operational_owner.py": (
        "owned_member_wait_timeout_and_process_tree_closure"
    ),
    # Semantic LSP session and the px/py_cert installed-operational counterpart reap their
    # Popen handles with a bounded wait; the timeout is enforced by the session owner.
    "runtime/semantic_lsp_process.py": ("bounded_session_wait_with_process_tree_closure"),
    "px/py_cert/scripts/run_installed_operational_owner.py": (
        "owned_member_wait_timeout_and_process_tree_closure"
    ),
}


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
        if (
            item.func.attr not in {"communicate", "wait"}
            or not isinstance(item.func.value, ast.Name)
            or item.func.value.id != handle
        ):
            continue
        timeout = next(
            (keyword.value for keyword in item.keywords if keyword.arg == "timeout"),
            None,
        )
        if timeout is not None:
            return f"{item.func.attr}(timeout={ast.unparse(timeout)})"
    return None


def _guarded_projection_calls(tree: ast.AST, relative: str) -> frozenset[str]:
    """Resolve actual canonical imported publisher names for effect inventory.

    An import alone creates no effect record and never proves call-path safety.
    Classification remains independently source reviewed and hash bound.
    """
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            canonical = node.level == 0 and node.module == "runtime.guarded_registry_projection"
            canonical_relative = (node.level == 1 and node.module == "guarded_registry_projection"
                                  and relative.startswith("runtime/")
                                  and relative.count("/") == 1)
            if canonical or canonical_relative:
                for alias in node.names:
                    if alias.name == "publish_guarded_registry_projection":
                        calls.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "runtime.guarded_registry_projection":
                    calls.add((alias.asname or alias.name) + ".publish_guarded_registry_projection")
    return frozenset(calls)


def _pure_string_replace_resolver(tree: ast.AST):
    """Exclude only exact built-in string methods, never inferred constructor types.

    Lexical name proof requires a single unconditional literal binding before
    the call. Unknown receivers, formatting, rebinding and dynamic scopes stay
    in the mutation census. Child calls are inventoried independently.
    """
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    scopes = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
    cache = {}

    def literal(node):
        return (isinstance(node, ast.Constant) and type(node.value) is str) or (
            isinstance(node, ast.JoinedStr)
            and all(isinstance(part, ast.Constant) and type(part.value) is str for part in node.values)
        )

    def scope_of(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, scopes):
                return node
        return tree

    def bindings(scope):
        if scope in cache:
            return cache[scope]
        blocked = set()
        stores = {}
        # Descendant rebinding is deliberately conservative, including nonlocal
        # and global assignments that could change a previously literal name.
        for item in ast.walk(scope):
            if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del)):
                stores.setdefault(item.id, []).append(item)
            elif isinstance(item, ast.arg):
                blocked.add(item.arg)
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item is not scope:
                blocked.add(item.name)
            elif isinstance(item, (ast.Global, ast.Nonlocal)):
                blocked.update(item.names)
            elif isinstance(item, (ast.Import, ast.ImportFrom)):
                if any(alias.name == '*' for alias in item.names):
                    cache[scope] = {}
                    return cache[scope]
                blocked.update(alias.asname or alias.name.split('.')[0] for alias in item.names)
            elif isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id in {'exec', 'eval', 'globals', 'locals', 'vars'}:
                cache[scope] = {}
                return cache[scope]
        result = {}
        for name, entries in stores.items():
            if name in blocked or len(entries) != 1:
                continue
            assignment = parents.get(entries[0])
            if not isinstance(assignment, (ast.Assign, ast.AnnAssign)) or parents.get(assignment) is not scope:
                continue
            targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
            if len(targets) == 1 and targets[0] is entries[0] and literal(assignment.value):
                result[name] = assignment
        cache[scope] = result
        return result

    def proven(call):
        if not isinstance(call.func, ast.Attribute) or call.func.attr != 'replace':
            return False
        # A caller-defined count conversion can execute arbitrary __index__.
        if call.keywords or any(isinstance(arg, ast.Starred) for arg in call.args):
            return False
        if len(call.args) > 2 and not (len(call.args) == 3 and isinstance(call.args[2], ast.Constant) and type(call.args[2].value) in (int, bool)):
            return False
        receiver = call.func.value
        if literal(receiver):
            return True
        if not isinstance(receiver, ast.Name):
            return False
        scope = scope_of(call)
        if isinstance(scope, (ast.ClassDef, ast.Lambda)):
            return False
        assignment = bindings(scope).get(receiver.id)
        if assignment is None:
            return False
        if isinstance(scope, ast.Module):
            # Other top-level statements/call expressions can rebind globals
            # without an AST Store in this file. Admit only the immediately
            # following standalone method call, with no evaluated annotation.
            statement = parents.get(call)
            if not isinstance(assignment, ast.Assign) or not isinstance(statement, ast.Expr) or statement.value is not call:
                return False
            index = scope.body.index(assignment)
            return index + 1 < len(scope.body) and scope.body[index + 1] is statement
        return (assignment.lineno, assignment.col_offset) < (call.lineno, call.col_offset)

    return proven


def _stream_effect_resolver(tree: ast.AST):
    """Conservatively inventory Python stream writes, without claiming custody.

    Unknown receivers/modes remain explicit unresolved candidates. Read-only
    handles are excluded only with a unique binding in their lexical scope.
    """
    open_aliases = {"open", "builtins.open", "io.open"}
    path_constructors = {"pathlib.Path"}
    os_writes = {"os.write"}
    for item in ast.walk(tree):
        if isinstance(item, ast.ImportFrom) and item.module in {"builtins", "io", "os"}:
            for alias in item.names:
                if alias.name == "open" and item.module != "os":
                    open_aliases.add(alias.asname or alias.name)
                if alias.name == "write" and item.module == "os":
                    os_writes.add(alias.asname or alias.name)
        elif isinstance(item, ast.ImportFrom) and item.module == "pathlib":
            path_constructors.update(alias.asname or alias.name for alias in item.names if alias.name == "Path")
        elif isinstance(item, ast.Import):
            for alias in item.names:
                if alias.name in {"builtins", "io"}:
                    open_aliases.add((alias.asname or alias.name) + ".open")
                if alias.name == "os":
                    os_writes.add((alias.asname or alias.name) + ".write")
                if alias.name == "pathlib":
                    path_constructors.add((alias.asname or alias.name) + ".Path")

    shadowed = {item.id for item in ast.walk(tree) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)}
    shadowed.update(item.arg for item in ast.walk(tree) if isinstance(item, ast.arg))
    shadowed.update(item.name for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    uncertain_open_aliases = {name for name in open_aliases if name.split('.', 1)[0] in shadowed}
    open_aliases -= uncertain_open_aliases
    path_constructors = {name for name in path_constructors if name.split('.', 1)[0] not in shadowed}

    def mode_of(value: ast.Call) -> str | None:
        name = _call_name(value)
        if name in uncertain_open_aliases:
            return "unresolved_open_receiver"
        if name not in open_aliases and not (isinstance(value.func, ast.Attribute) and value.func.attr == "open"):
            return None
        if any(isinstance(arg, ast.Starred) for arg in value.args):
            return "unresolved_open_mode"
        mode = next((k.value for k in value.keywords if k.arg == "mode"), None)
        # Bound Path.open starts with mode; builtins/io open start with file.
        index = 1 if name in open_aliases else 0
        if mode is None and len(value.args) > index:
            mode = value.args[index]
        if mode is None and any(k.arg is None for k in value.keywords):
            return "unresolved_open_mode"
        readonly = mode is None or isinstance(mode, ast.Constant) and mode.value in {"r", "rb", "rt"}
        if readonly:
            if name in open_aliases:
                return "read_only"
            receiver = value.func.value
            if isinstance(receiver, ast.Call) and _call_name(receiver) in path_constructors:
                return "read_only"
            return "unresolved_open_receiver"
        if not isinstance(mode, ast.Constant) or not isinstance(mode.value, str):
            return "unresolved_open_mode"
        if any(c in mode.value for c in "wax+"):
            return "writable_open_mode"
        return "unresolved_open_mode"

    def resolve(node: ast.Call) -> str | None:
        call = _call_name(node)
        leaf = call.rsplit(".", 1)[-1]
        opened = mode_of(node)
        if opened is not None:
            return None if opened == "read_only" else opened
        if call in os_writes:
            return "descriptor_write"
        if leaf not in {"write", "writelines"} or not isinstance(node.func, ast.Attribute):
            return None
        receiver = node.func.value
        if isinstance(receiver, ast.Call) and mode_of(receiver) == "read_only":
            return None
        if isinstance(receiver, ast.Name):
            scopes = [s for s in ast.walk(tree) if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
                      and s.lineno <= node.lineno <= getattr(s, "end_lineno", s.lineno)]
            scope = min(scopes, key=lambda s: getattr(s, "end_lineno", s.lineno) - s.lineno) if scopes else tree
            bindings = []
            for item in ast.walk(scope):
                if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id == receiver.id:
                    bindings.append(item)
            if len(bindings) == 1:
                binding = bindings[0]
                for item in ast.walk(scope):
                    value = None
                    if isinstance(item, (ast.Assign, ast.AnnAssign)):
                        targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                        if any(t is binding for t in targets): value = item.value
                    elif isinstance(item, ast.withitem) and item.optional_vars is binding:
                        value = item.context_expr
                    if isinstance(value, ast.Call) and mode_of(value) == "read_only":
                        return None
        return "unresolved_stream_receiver"
    return resolve


def discover_effect_surfaces(root: Path) -> list[dict[str, Any]]:
    root = root.resolve()
    records = []
    source_walk = bounded_walk(
        root,
        limits=WalkLimits(max_files=100_000, max_depth=128, max_bytes=2 * 1024**3),
        symlink_policy="skip",
        exclude=is_external_environment_relative,
    )
    for entry in source_walk.files:
        path = entry.path
        relative = entry.relative
        if (
            path.suffix.casefold() != ".py"
            or "__pycache__" in path.parts
            or relative.startswith("tests/")
            or relative.startswith(".px/preserved-skills/")
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        guarded_projection_calls = _guarded_projection_calls(tree, relative)
        stream_effect = _stream_effect_resolver(tree)
        pure_string_replace = _pure_string_replace_resolver(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call = _call_name(node)
            leaf = call.rsplit(".", 1)[-1]
            stream_diagnostic = stream_effect(node)
            if pure_string_replace(node):
                continue
            if call in PROCESS_CALLS:
                effect = "process"
            elif call.startswith(NETWORK_PREFIXES):
                effect = "network"
            elif call in guarded_projection_calls:
                effect = "filesystem_mutation"
            elif leaf in MUTATION_NAMES or call == "os.remove":
                effect = "filesystem_mutation"
            elif stream_diagnostic is not None:
                effect = "filesystem_mutation"
            else:
                continue
            keywords = {
                str(item.arg): ast.unparse(item.value)
                for item in node.keywords
                if item.arg
            }
            process_timeout = keywords.get("timeout")
            if call == "subprocess.Popen":
                process_timeout = _popen_communication_timeout(tree, node)
                if relative == RESOURCE_LIFECYCLE_OWNER:
                    process_timeout = "owned_resource_lifecycle_process_tree_receipt"
                elif relative in OWNED_PROCESS_SUPERVISORS:
                    process_timeout = OWNED_PROCESS_SUPERVISORS[relative]
            # Identity is a source locator, not an interpreter serialization.
            # ast.dump() changes when Python adds AST fields (for example
            # type_params in 3.12), which made the same bytes produce different
            # ownership IDs across supported runtimes.
            semantic = f"{relative}:{node.lineno}:{node.col_offset}:{call}"
            records.append(
                {
                    "id": hashlib.sha256(semantic.encode()).hexdigest()[:20],
                    "path": relative,
                    "line": node.lineno,
                    "call": call,
                    "effect": effect,
                    "owner": relative.split("/", 1)[0],
                    "policy": (
                        "policies/resource-lifecycle-retention.json"
                        if relative == RESOURCE_LIFECYCLE_OWNER
                        else "policies/contained-execution.json"
                        if effect in {"process", "network"}
                        else RECOVERABLE_RECLAMATION_OWNERS[relative]
                        if relative in RECOVERABLE_RECLAMATION_OWNERS
                        else "policies/artifact-preservation.json"
                    ),
                    "approval": "required_for_material_or_external_effects",
                    "containment": "validated_path_and_bounded_scope",
                    "timeout": process_timeout if effect == "process" else None,
                    "shell": keywords.get("shell"),
                    "destructive": leaf in DESTRUCTIVE_NAMES or call == "os.remove",
                    **({"stream_discovery": stream_diagnostic} if stream_diagnostic is not None else {}),
                }
            )
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
                errors.append(
                    f"{record['path']}:{record['line']}: unsafe shell execution"
                )
            if record["timeout"] is None:
                errors.append(
                    f"{record['path']}:{record['line']}: process call lacks timeout"
                )
        if (
            record["destructive"]
            and record["path"] != RESOURCE_LIFECYCLE_OWNER
            and record["path"] not in RECOVERABLE_RECLAMATION_OWNERS
        ):
            errors.append(
                f"{record['path']}:{record['line']}: hard-delete surface is prohibited"
            )
    counts: dict[str, int] = {}
    for record in actual:
        counts[record["effect"]] = counts.get(record["effect"], 0) + 1
    # Phase 1C: every mutating producer must be classified (leased or exempt with
    # a proven reason). An unclassified producer fails the effect-surface gate.
    try:
        from .mutating_producer_registry import validate_registry

        producer_report = validate_registry(root)
    except Exception as error:  # pragma: no cover - defensive, fails closed
        producer_report = {
            "valid": False,
            "errors": [f"mutating producer registry could not be evaluated: {error}"],
        }
    if not producer_report.get("valid", False):
        for error in producer_report.get("errors", []) or [
            "mutating producer registry is invalid"
        ]:
            errors.append(f"mutating-producer: {error}")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "record_count": len(actual),
        "counts": dict(sorted(counts.items())),
        "errors": errors,
        "records": actual,
        "mutating_producers": {
            "valid": bool(producer_report.get("valid")),
            "discovered": producer_report.get("discovered"),
            "counts": producer_report.get("counts"),
        },
    }
