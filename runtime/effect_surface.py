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
    # Bare `copy` is deliberately absent. `list.copy()`/`dict.copy()`/`array.copy()`
    # outnumber file copies, and discovery records only the leaf name, so a collection
    # copy inside a sort or a hash-cache path was inventoried as a filesystem write
    # and then treated as a rename-shaped mutation. Qualified copies arrive as
    # `copy2`, `copytree`, `shutil.copy` or `shutil.copyfile`. Discovery therefore
    # resolves the *qualified* file-copy names explicitly (see FILE_COPY_CALLS) and
    # still refuses a bare `.copy()` unless its receiver is a proven path or module.
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
# A qualified file copy always materializes bytes at its destination. `shutil.copyfile`
# was missing from MUTATION_NAMES entirely, so two real writes in
# `scripts/clean_source_export.py` were absent from the canonical census. These names are
# matched exactly as the scanner's dotted call name, never as the bare leaf, so
# `value.copy()` from a list or dict is unaffected.
FILE_COPY_CALLS = frozenset({
    "shutil.copy",
    "shutil.copyfile",
    "shutil.copy2",
    "shutil.copyfileobj",
    "shutil.copytree",
})
SHUTIL_COPY_IMPORT_FUNCTIONS = frozenset({"copy", "copyfile", "copy2", "copyfileobj", "copytree"})
# Bare `copy` stays out of the census for collections. A receiver that is syntactically a
# `pathlib.Path` expression is a file copy, so it is admitted under its exact form.
PATH_MODULE_LEAVES = frozenset({"pathlib.Path", "Path"})
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
    # The atomic publisher stages one random exclusive `.<name>.<uuid>.prepared`
    # image and publishes it by os.replace; its finally block removes only that
    # owned unpublished staging path. The destination image is never deleted.
    "runtime/secure_publish.py": "policies/artifact-preservation.json",
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


# Builtin str methods that return a str; used only to chain a proven str source.
_STR_RESULT_METHODS = frozenset(
    {
        "strip", "lstrip", "rstrip", "lower", "upper", "casefold", "title",
        "capitalize", "swapcase", "format", "format_map", "replace", "join",
        "zfill", "center", "ljust", "rjust", "expandtabs", "removeprefix",
        "removesuffix", "translate",
    }
)
# Methods that return `str` for *any* receiver, so a proven-`str` receiver is not required.
# `isoformat()` is the standard-library case: datetime, date and time all return `str` from it.
# Restricting this set to methods the standard library defines that way keeps it a grammar
# fact rather than a type inference.
_STR_RETURNING_FOR_ANY_RECEIVER = frozenset({"isoformat"})


def _pure_string_replace_resolver(tree: ast.AST):
    """Exclude only exact built-in string methods, never inferred constructor types.

    Lexical name proof requires a single unconditional literal binding before
    the call. Unknown receivers, formatting, rebinding and dynamic scopes stay
    in the mutation census. Child calls are inventoried independently.
    """
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    scopes = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
    cache = {}
    # Must exist before scope_of/bindings run: they call annotations(), which reads
    # these caches. Defining them later bound them too late to be initialised.
    annotation_cache = {}
    enclosing = parents
    yields_string = {}

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

    def generator_yields_str(function):
        """True when every `yield` in this function yields a statically str value.

        Only a bare `str` parameter/subscript (`text[start:]`), a proven-`str` name, a
        string literal, or a `bytes`-decoding call is admitted. Any other yield shape
        — including a yielded call whose return type is unknown — refutes the proof,
        so an unknown decoder is never treated as a string producer.
        """
        if function in yields_string:
            return yields_string[function]
        yields_string[function] = False
        names = annotations(function)
        for item in ast.walk(function):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item is not function:
                continue
            if not isinstance(item, ast.Yield) and not (
                isinstance(item, ast.YieldFrom)
            ):
                continue
            value = item.value
            ok = False
            if literal(value):
                ok = True
            elif isinstance(value, ast.Name):
                ok = names.get(value.id) == "str"
            elif isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name):
                ok = names.get(value.value.id) == "str"
            elif (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr == "decode"
                and isinstance(value.func.value, ast.Name)
                and value.func.value.id == "bytes"
                and not value.keywords
            ):
                # Only the builtin `bytes(...).decode()` is statically str. An
                # arbitrary `decoder.decode(...)` has an unknown return type and must
                # refute the proof rather than be assumed to produce text.
                ok = True
            if not ok:
                yields_string[function] = False
                return False
        yields_string[function] = True
        return True

    parents_of_tree = enclosing

    def annotations(scope):
        """Map parameter name -> exact annotation text for this lexical scope."""
        if scope in annotation_cache:
            return annotation_cache[scope]
        result = {}
        arguments = getattr(scope, "args", None)
        if arguments is not None:
            for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]:
                if arg.annotation is not None:
                    result[arg.arg] = ast.unparse(arg.annotation)
        annotation_cache[scope] = result
        return result

    def _str_source(receiver, literal, annotations):
        """True only when `receiver` is a builtin-str value by construction."""
        if literal(receiver):
            return True
        if (isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name)
                and receiver.func.id == "str" and not receiver.keywords
                and len(receiver.args) <= 1):
            return True
        if isinstance(receiver, ast.Name):
            scope = scope_of(receiver)
            if not isinstance(scope, (ast.ClassDef, ast.Lambda)):
                return annotations(scope).get(receiver.id) == "str"
        return False

    def loop_bound_str(name, call):
        """`for name in gen():` where `gen` provably yields only str.

        This is a syntactic binding, not type inference: the iterable must be a
        direct call to a function defined in this module whose every yield is provably
        str. A rebound name, a second binding, or an unknown iterable refutes it.
        """
        node = call
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.For, ast.AsyncFor)):
                if (not isinstance(node.target, ast.Name) or node.target.id != name
                        or not isinstance(node.iter, ast.Call)
                        or not isinstance(node.iter.func, ast.Name)):
                    return False
                function = next(
                    (n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == node.iter.func.id), None)
                if function is None or not generator_yields_str(function):
                    return False
                # Any other binding of the loop name in the enclosing scope refutes it.
                scope = scope_of(call)
                stores = [
                    item for item in ast.walk(scope)
                    if isinstance(item, ast.Name) and item.id == name
                    and isinstance(item.ctx, (ast.Store, ast.Del))
                    and item is not node.target
                ]
                return not stores
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return False
        return False

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
        # `str(x).replace(...)` is always a string operation: built-in str() returns
        # exactly str, whatever x is. Only the zero-or-one-argument, keyword-free
        # form is admitted so an encoding/errors override stays in the census.
        if (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Name)
            and receiver.func.id == "str"
            and not receiver.keywords
            and len(receiver.args) <= 1
            and not any(isinstance(arg, ast.Starred) for arg in receiver.args)
        ):
            return True
        # `datetime(...).isoformat().replace(...)` is a string operation regardless of the
        # receiver's own type, because `isoformat()` returns `str` for every type that defines
        # it in the standard library. Without this the read was counted as a filesystem
        # mutation by method name alone.
        if (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Attribute)
            and receiver.func.attr in _STR_RETURNING_FOR_ANY_RECEIVER
            and not receiver.keywords
            and not any(isinstance(arg, ast.Starred) for arg in receiver.args)
        ):
            return True
        # `str(x).strip().replace(...)`: a str-returning method called on a proven str
        # source is itself str. Only exact builtin str methods with no keywords are
        # admitted, so a caller-defined method of the same name is not inferred.
        if (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Attribute)
            and receiver.func.attr in _STR_RESULT_METHODS
            and not receiver.keywords
            and not any(isinstance(arg, ast.Starred) for arg in receiver.args)
            and _str_source(receiver.func.value, literal, annotations)
        ):
            return True
        if not isinstance(receiver, ast.Name):
            return False
        scope = scope_of(call)
        if isinstance(scope, (ast.ClassDef, ast.Lambda)):
            return False
        # A parameter annotated exactly `str` is str at every call site; the callee
        # cannot rebind a parameter annotation. Rebinding is checked by bindings(),
        # which only returns literal assignments, so annotated names are handled here.
        if annotations(scope).get(receiver.id) == "str":
            return True
        if loop_bound_str(receiver.id, call):
            return True
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

    def _path_bound_name(identifier: str, call: ast.Call) -> bool:
        """True when `identifier` is a single-assignment local holding a path expression.

        Provenance only, not type inference. The name must be assigned exactly once, in an
        enclosing scope, from a call to a path constructor, a division/joinpfath of one, or
        another name that already satisfies this. Any rebinding, any parameter, and any
        value of unknown shape refutes it, so an ambiguous receiver stays unresolved.

        An explicit read mode is still required by the caller; this never turns a write into
        a read, it only stops a proven read from being reported as an unresolved mutator.
        """

        def pathish(node: ast.AST, seen: frozenset[str] = frozenset()) -> bool:
            if isinstance(node, ast.Call):
                return _call_name(node) in path_constructors
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                return pathish(node.left, seen) or pathish(node.right, seen)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                return node.func.attr in {"joinpath", "resolve", "absolute"}
            if isinstance(node, ast.Name):
                return _path_parameter(node.id, seen)
            return False

        def _path_parameter(identifier: str, seen: frozenset[str]) -> bool:
            """True when every binding of `identifier` is a `Path`-annotated parameter.

            A path built from a path parameter (`root / LEDGER`) is still a path. The
            annotation must be exactly `Path`; a `str | Path` union or an unannotated
            parameter proves nothing and is refused, keeping an ambiguous receiver
            unresolved rather than silently read.
            """
            if identifier in seen:
                return False
            parameters = [item for item in ast.walk(tree)
                          if isinstance(item, ast.arg) and item.arg == identifier]
            if not parameters:
                return False
            return all(item.annotation is not None
                       and ast.unparse(item.annotation) in {"Path", "pathlib.Path"}
                       for item in parameters)

        assignments = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == identifier
            and isinstance(node.ctx, ast.Store)
        ]
        if len(assignments) != 1:
            return False
        if any(item.arg == identifier for item in ast.walk(tree) if isinstance(item, ast.arg)):
            return False
        parents_of = {child: node for node in ast.walk(tree)
                      for child in ast.iter_child_nodes(node)}
        assignment = parents_of.get(assignments[0])
        if not isinstance(assignment, (ast.Assign, ast.AnnAssign)):
            return False
        return pathish(assignment.value)

    def mode_of(value: ast.Call) -> str | None:
        name = _call_name(value)
        if name in uncertain_open_aliases:
            return "unresolved_open_receiver"
        if name not in open_aliases and not (isinstance(value.func, ast.Attribute) and value.func.attr == "open"):
            return None
        if any(isinstance(arg, ast.Starred) for arg in value.args):
            return "unresolved_open_mode"
        mode = next((k.value for k in value.keywords if k.arg == "mode"), None)
        # A method call's first argument is the mode; only builtins/io.open start with the
        # file. `_call_name` drops a receiver that is not a plain name, so a bound open on
        # a path expression (`(root / 'x').open('w')`, `ledger.open('r')`) is named exactly
        # `open` and was indexed like the builtin: the *file* argument was read as the mode.
        # For `ledger.open('r')` that meant the read was reported as an unresolved receiver
        # and the producer was counted as a mutator. The receiver decides, not the name.
        bound = isinstance(value.func, ast.Attribute) and value.func.attr == "open"
        index = 0 if bound else (1 if name in open_aliases else 0)
        if mode is None and len(value.args) > index:
            mode = value.args[index]
        # `_call_name` drops a receiver that is not a plain name, so a bound open on a
        # path expression (`(root / 'x').open('w')`) is named exactly `open` and was
        # indexed like the builtin: the target expression was read as the mode, found
        # non-literal, and the write was silently dropped from the census. It is a
        # method call, whose first argument is the mode.
        if mode is None and bound and value.args:
            mode = value.args[0]
            # An explicit read mode on a bound open is a read, whoever the receiver is:
            # `Path(...).open('r')` and `config.open('rb')` create nothing and change
            # nothing. Reporting them invented mutation sites that were then matched
            # against the first `write_text` in the same function and credited to it.
            if isinstance(mode, ast.Constant) and mode.value in {"r", "rb", "rt"}:
                return "read_only"
        if mode is None and any(k.arg is None for k in value.keywords):
            return "unresolved_open_mode"
        readonly = mode is None or isinstance(mode, ast.Constant) and mode.value in {"r", "rb", "rt"}
        if readonly:
            if name in open_aliases:
                return "read_only"
            receiver = value.func.value
            if isinstance(receiver, ast.Call) and _call_name(receiver) in path_constructors:
                return "read_only"
            # `ledger = root / LEDGER` then `ledger.open("r")`: the receiver is a plain name
            # that provably holds a Path, assigned once from a path expression. Without this
            # the read was reported as an unresolved receiver and the producer was counted
            # as a mutator. Only a single-assignment local whose value is a path expression
            # qualifies; an ambiguous or reassigned name stays unresolved.
            if isinstance(receiver, ast.Name) and _path_bound_name(receiver.id, value):
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
            # A handle written through is a durable write unless it is proven read-only.
            # The previous rule admitted the write only when it found *one* binding, so
            # a handle variable reused in a second `with` block lost its record and the
            # writes through it vanished from the census. An opened handle is admitted
            # when every binding of the name is a read-only open; anything else stays a
            # write. Unknown receivers are still reported for review.
            values = []
            for binding in bindings:
                for item in ast.walk(scope):
                    value = None
                    if isinstance(item, (ast.Assign, ast.AnnAssign)):
                        targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                        if any(t is binding for t in targets): value = item.value
                    elif isinstance(item, ast.withitem) and item.optional_vars is binding:
                        value = item.context_expr
                    if value is not None:
                        values.append(value)
            if values and len(values) == len(bindings) and all(
                isinstance(value, ast.Call) and mode_of(value) == "read_only"
                for value in values
            ):
                return None
            if values:
                return "handle_write"
        return "unresolved_stream_receiver"
    return resolve


def _is_shutil_module_receiver(call: str, tree: ast.AST) -> bool:
    """True when a bare-leaf file-copy call is qualified on the `shutil` module.

    The qualification alone is not proof: a local or parameter named `shutil` renders
    identically. The name is admitted only when this module imports shutil under that
    exact name and never rebinds it.
    """
    if call.rsplit(".", 1)[0].split(".")[-1] != "shutil":
        return False
    imported = any(
        isinstance(item, ast.Import) and any(alias.name == "shutil" and alias.asname in (None, "shutil") for alias in item.names)
        for item in ast.walk(tree)
    )
    if not imported:
        return False
    return not any(
        isinstance(item, ast.Name) and item.id == "shutil" and isinstance(item.ctx, ast.Store)
        for item in ast.walk(tree)
    )


def _path_receiver_copy(node: ast.Call) -> bool:
    """True for `<Path expression>.copy(...)`: a copy method on a proven path value.

    `shutil.copy` is matched by its qualified name. The method form
    `Path('a').copy('b')` (Python 3.14) carries only the leaf `copy`, which is also the
    name of `list.copy` and `dict.copy`. Only a syntactically constructed `pathlib.Path`
    receiver, or a module alias named `shutil`, is admitted; every other receiver keeps
    the old behavior of not being a mutation.
    """
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "copy":
        return False
    receiver = node.func.value
    if isinstance(receiver, ast.Call) and (
        _call_name(receiver) in PATH_MODULE_LEAVES
        or (isinstance(receiver.func, ast.Attribute) and _call_name(receiver) == "pathlib.Path")
    ):
        return True
    return False


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
            # PX-OS-1067 evidence tooling under docs/repair/evidence/ reads and writes only
            # the exact artifacts its governed admission names. It is audit scaffolding, not
            # a product producer, and excluding it here is required for census stability:
            # a census launcher living inside the scanned tree otherwise changes the scan
            # denominator that it is measuring. Restricted to that one directory on purpose.
            or relative.startswith("docs/repair/evidence/")
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        guarded_projection_calls = _guarded_projection_calls(tree, relative)
        stream_effect = _stream_effect_resolver(tree)
        pure_string_replace = _pure_string_replace_resolver(tree)
        # Per-file occurrence counter for locator collisions; see the id comment below.
        locator_ordinals: dict[str, int] = {}
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
            elif call in FILE_COPY_CALLS or call == "os.remove":
                effect = "filesystem_mutation"
            elif leaf in MUTATION_NAMES:
                effect = "filesystem_mutation"
            elif leaf in {"copyfile", "copyfileobj"} and _is_shutil_module_receiver(call, tree):
                # `shutil.copyfile` / `shutil.copyfileobj` write bytes at the destination
                # and were previously absent from the census in every qualified form.
                # The bare leaf is admitted only when this module imports shutil under
                # exactly that name and never rebinds it; a shadowed `shutil` renders
                # identically and stays a caller-defined call with unknown behavior.
                effect = "filesystem_mutation"
            elif leaf == "copy" and _path_receiver_copy(node):
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
            #
            # A chained call such as `a.replace(x).replace(y)` reports distinct calls
            # with the same line *and* column, so a bare path:line:col:call locator
            # collided and two ownership records shared one id. The locator keeps its
            # meaning and gains a deterministic occurrence ordinal scoped to that
            # locator, which is `ast.walk` order (breadth-first from the module, and
            # therefore stable for identical bytes on a supported interpreter).
            locator = f"{relative}:{node.lineno}:{node.col_offset}:{call}"
            ordinal = locator_ordinals.get(locator, 0)
            locator_ordinals[locator] = ordinal + 1
            semantic = locator if ordinal == 0 else f"{locator}#{ordinal}"
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
    # Identity must be unique in the current discovery and in the published image.
    # Without this a locator collision made two distinct mutation sites share one
    # ownership record id, and the staleness comparison below could not see it.
    for label, records in (("discovered", actual), ("published", registry.get("records") or [])):
        seen: dict[str, int] = {}
        for record in records:
            seen[record["id"]] = seen.get(record["id"], 0) + 1
        collisions = sorted(key for key, count in seen.items() if count > 1)
        if collisions:
            errors.append(
                f"{label} effect-surface records have duplicate ids: {collisions[:5]}"
            )
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

        producer_report = validate_registry(root, records=actual)
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
