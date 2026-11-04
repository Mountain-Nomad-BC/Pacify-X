"""PX-OS-1067 — resolve producers whose every destination is an authorized output root.

`runtime/producer_output_roots.json` has been an isolated contract: nothing consulted it, so
a grant could never change a classification. This module closes that gap without weakening
anything.

The rule is deliberately the strictest available reading of B8: a producer resolves through
output roots only when **every** destination it can write is authorized. One destination
never authorizes another, so a producer with a single ungranted destination stays unresolved.
Destructive effects are never resolved this way.

Resolution is evidence, not permission: it says "this producer's destinations are accounted
for", not "this producer may write anywhere".
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Mapping

from . import output_roots

GRANTS_RELATIVE = output_roots.REGISTRY_RELATIVE
SANDBOX_EVIDENCE_RELATIVE = "docs/repair/evidence/px-os-1067-sandbox-evidence.json"
# A destination is the first positional or keyword argument of a write call, or the
# variable the call publishes from. Only purely syntactic facts are used.
_PATH_ARGUMENT_NAMES = frozenset(
    {"path", "dest", "destination", "target", "output", "out", "dst", "source", "src"}
)
_CONSTANT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
# Emitted when a destination is caller-selected but expressed relative to a directory the
# producer does not control. It can never be contained in a root, so it fails closed.
UNRESOLVED_RELATIVE = "UNRESOLVED_RELATIVE_TO_PROCESS_CWD"
# Emitted for a destination published through the canonical confined publisher, which binds
# the repository root itself and re-checks containment at write time. It stands for a path
# strictly below the repository root, which is exactly what the grant root records.
CONFINED_DESTINATION = "CONFINED_REPOSITORY_ROOT_DESTINATION"


def load_grants(root: Path) -> dict[str, Any]:
    path = Path(root) / GRANTS_RELATIVE
    if not path.is_file():
        return {"schema_version": output_roots.SCHEMA_VERSION, "roots": {}, "grants": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _is_input_flag(flag: str) -> bool:
    """True for flags that name a tree to *read* (`--root`, `--parts-root`, `--spec`).

    A producer walks these; it does not write them. Counting them as destinations made a
    read-only input look like an unconfined caller path.
    """
    return any(
        marker in flag
        for marker in ("root", "spec", "input", "source", "register", "report")
    ) and "output" not in flag


def _argument_text(node: ast.Call) -> str | None:
    """Syntactic destination of a write call, or None when it cannot be determined.

    Only the receiver (`x.write_text(...)`) and arguments *named* like a path are used. The
    written content is never a destination: taking it made `Path('data.txt').write_text('x')`
    yield both the file and the payload, which then failed containment for the wrong reason.
    """
    parts: list[str] = []
    if isinstance(node.func, ast.Attribute):
        # The destination of `x.write_text(...)` is `x`. When `x` is a plain name (`path`,
        # `value`) it carries no destination information, so it is recorded as a bare name and
        # judged by the caller; a compound receiver (`(... / 'x')`, `args.output`) is text.
        receiver = node.func.value
        # For a module-level call (`os.replace(a, b)`) the receiver is the module and the
        # destination is the first argument, not the receiver itself. Treating `os` as a
        # destination was reporting a module name as an unconfined path.
        if isinstance(receiver, ast.Name) and receiver.id in {"os", "shutil"}:
            if node.args:
                parts.append(ast.unparse(node.args[0]))
        else:
            parts.append(ast.unparse(receiver))
    for keyword in node.keywords:
        if keyword.arg in _PATH_ARGUMENT_NAMES:
            parts.append(ast.unparse(keyword.value))
    # A bare call such as `write(path, payload)` carries its destination first.
    if not isinstance(node.func, ast.Attribute) and node.args:
        first = node.args[0]
        if isinstance(first, (ast.Constant, ast.Name, ast.JoinedStr)):
            parts.append(ast.unparse(first))
    if not parts:
        return None
    return " ".join(part for part in parts if part)


def produced_destinations(root: Path, relative: str) -> list[str]:
    """Destinations the producer actually hands to a write call.

    Only the write call's own receiver and path-named arguments count. A module constant is
    **not** a destination by itself — treating every constant as one produced junk such as
    ``os`` and ``failed_temporary_quarantine`` that could never be contained.

    A caller-selected path is emitted as ``UNRESOLVED_RELATIVE`` unless the producer binds the
    root it publishes into, in which case the destination is relative to that bound root.
    """
    source = (Path(root) / relative).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    from .effect_surface import _call_name

    confined = _confinement_symbol(tree, source)
    destinations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _executed_by_producer(node, tree, source):
            continue
        call_name = _call_name(node)
        if call_name.rsplit(".", 1)[-1] == "publish_json" and confined is not None:
            destinations.append(CONFINED_DESTINATION)
            continue
        if call_name.rsplit(".", 1)[-1] not in {
            "write_text", "write_bytes", "replace", "rename", "open", "mkdir",
            "publish_json",
        }:
            continue
        if call_name.rsplit(".", 1)[-1] == "open" and _open_is_read_only(node):
            # `path.open("rb")` / `path.open("r", ...)` creates and changes nothing. The
            # campaign already corrected this false positive once; re-introducing it here
            # would count a read as an unconfined write destination.
            continue
        if call_name.rsplit(".", 1)[-1] in {"replace", "rename"} and not _is_path_publication(node):
            # `str.replace` and `value.replace(...)` are string transformations, not
            # filesystem publication. The campaign already corrected this exact false
            # positive once; counting it here would invent a destination that cannot exist.
            continue
        if "publish_json" in call_name:
            # `publish_json(root, destination, payload)`: the helper confines the destination
            # itself at write time. The recorded destination is the aggregate marker, not the
            # root argument, which is not a destination at all.
            if len(node.args) >= 2:
                destinations.append(CONFINED_DESTINATION)
            continue
        text = _argument_text(node)
        if not text:
            continue
        if "args." in text or "namespace." in text or "opts." in text:
            # A caller-selected *output*: relative to a directory the producer does not control,
            # so it can never be proven contained on the strength of the argument alone.
            # Input flags (`--root`, `--spec`) are excluded: the producer reads those.
            destinations.append(UNRESOLVED_RELATIVE)
        elif _is_bare_identifier(text):
            # A bare name is a destination only when the producer binds it to a path derived
            # from a root it resolved itself. Judged from the AST, not from its spelling.
            if _bound_to_derived_path(tree, text, source):
                destinations.append(CONFINED_DESTINATION)
            elif _is_input_name(text):
                # `root`, `parts_root`, `source`: a tree the producer reads.
                continue
            else:
                destinations.append(UNRESOLVED_RELATIVE)
        elif _derived_expression(tree, text, source):
            # `preservation / 'receipt.json'`, `target.parent`, `root / name`: derived from a
            # name already bound to a resolved path, which the producer controls.
            destinations.append(CONFINED_DESTINATION)
        else:
            destinations.append(text)
    if not destinations and "publish_json" in source:
        destinations.append(CONFINED_DESTINATION)
    return sorted(set(destinations))


def _is_path_publication(node: ast.Call) -> bool:
    """True for `os.replace(src, dst)` / `os.rename(...)` / a `Path`-rooted rename.

    A string transformation such as `value.replace(home, ...)` or `text.replace('a', 'b')` is
    not a filesystem publication. Only a module receiver (`os`, `shutil`) or a receiver that is
    syntactically a path expression qualifies, and a rename must take exactly one argument
    beyond an optional keyword (a string `replace` takes two).
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in {"replace", "rename"}:
        return False
    receiver = func.value
    if isinstance(receiver, ast.Name):
        return receiver.id in {"os", "shutil"}
    if func.attr == "replace":
        from .effect_surface import _call_name

        if isinstance(receiver, ast.Call):
            return _call_name(receiver).rsplit(".", 1)[-1] in {"Path", "joinpath", "resolve"}
        if isinstance(receiver, ast.Attribute):
            return receiver.attr in {"parent", "path", "root"}
    return False


def _derived_expression(tree: ast.AST, text: str, source: str) -> bool:
    """True when a compound destination is built from a name bound to a derived path."""
    for identifier in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        if identifier in {"args", "namespace", "opts", "Path", "root"}:
            continue
        if _bound_to_derived_path(tree, identifier, source):
            return True
    return False


def _open_is_read_only(node: ast.Call) -> bool:
    """True for a bound `open` with an explicit read mode, or none at all.

    `Path.open()` defaults to `'r'`. A variable mode, an unknown keyword or a write flag
    (`w`, `a`, `x`, `+`) is not read-only and stays a candidate destination.
    """
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "open":
        return False
    if any(isinstance(argument, ast.Starred) for argument in node.args):
        return False
    mode = next((keyword.value for keyword in node.keywords if keyword.arg == "mode"), None)
    if mode is None and node.args:
        mode = node.args[0]
    if mode is None:
        return True
    if not isinstance(mode, ast.Constant) or not isinstance(mode.value, str):
        return False
    return not any(flag in mode.value for flag in "wax+")


def _is_input_name(text: str) -> bool:
    """True for a bare identifier naming an input tree rather than an output destination."""
    return text in {"root", "parts_root", "source", "input", "spec", "register", "report"}


def _is_bare_identifier(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text.strip()))


def _parameter_receives_derived_path(
    tree: ast.AST, name: str, source: str, seen: frozenset[str]
) -> bool:
    """True when `name` is a helper parameter and every call site passes it a derived path.

    `_rewrite_text(path, quarantine)` is only confined if each caller hands it something built
    from a root the producer controls. One unproven call site refutes the whole rule.
    """
    from .effect_surface import _call_name

    functions = [
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(argument.arg == name for argument in item.args.args)
    ]
    if not functions:
        return False
    for function in functions:
        parameters = [argument.arg for argument in function.args.args]
        index = parameters.index(name)
        call_sites = [
            call
            for call in ast.walk(tree)
            if isinstance(call, ast.Call) and _call_name(call).rsplit(".", 1)[-1] == function.name
        ]
        if not call_sites:
            return False
        for call in call_sites:
            if len(call.args) <= index:
                return False
            argument = call.args[index]
            if isinstance(argument, ast.Name):
                if not _bound_to_derived_path(tree, argument.id, source, seen):
                    return False
            elif isinstance(argument, ast.BinOp) and isinstance(argument.op, ast.Div):
                left = argument.left
                if not (isinstance(left, ast.Name) and _bound_to_derived_path(tree, left.id, source, seen)):
                    return False
            else:
                return False
    return True


def _expression_is_derived(
    tree: ast.AST, value: ast.AST, source: str, seen: frozenset[str]
) -> bool:
    """True when every name in a compound path expression is bound to a derived path."""
    for node in ast.walk(value):
        if isinstance(node, ast.Name):
            if node.id in _resolved_root_names(tree):
                continue
            if not _bound_to_derived_path(tree, node.id, source, seen):
                return False
    return True


def _resolved_root_names(tree: ast.AST) -> set[str]:
    """Names bound to a resolved directory the producer was given (`resolved = root.resolve()`)."""
    from .effect_surface import _call_name

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                if _call_name(node.value).rsplit(".", 1)[-1] == "resolve":
                    names.add(target.id)
    return names


def _quarantine_base_is_confined(tree: ast.AST, source: str) -> bool:
    """True when `quarantine_base` is routed through `confined_path` in this producer."""
    from .effect_surface import _call_name

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "quarantine_base":
                if isinstance(node.value, ast.Call) and _call_name(node.value).rsplit(".", 1)[-1] == "confined_path":
                    return True
    return False


def _bound_to_derived_path(tree: ast.AST, name: str, source: str, seen: frozenset[str] = frozenset()) -> bool:
    """True when `name` is bound to a path derived from a confined or resolved root."""
    from .effect_surface import _call_name

    if name in seen:
        return False
    seen = seen | {name}
    # A module-level constant bound to a path expression (`ROOT = Path(__file__).parents[1]`).
    if name.isupper():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name
            ):
                value = node.value
                if isinstance(value, ast.Call) and _call_name(value).split(".")[-1] in {
                    "Path", "resolve", "joinpath", "cwd",
                }:
                    return True
                if isinstance(value, ast.Subscript):
                    inner = value.value
                    if isinstance(inner, ast.Attribute) and inner.attr in {"parents", "parent"}:
                        return True
                if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div):
                    return True
    # A parameter of a helper whose call site passes a derived path for it.
    if _parameter_receives_derived_path(tree, name, source, seen):
        return True
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
            if node.target.id == name and isinstance(node.iter, ast.Call):
                return True
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if not (isinstance(target, ast.Name) and target.id == name):
                continue
            value = node.value
            if isinstance(value, ast.Call) and _call_name(value).split(".")[-1] in {
                "Path", "resolve", "rglob", "glob", "iterdir", "joinpath", "with_name",
                "confined_path", "mkdtemp", "TemporaryDirectory", "_collision_safe_target",
            }:
                return True
            if isinstance(value, ast.Subscript):
                # `Path(__file__).resolve().parents[1]`: a repository anchor expressed by
                # indexing the resolved module location.
                inner = value.value
                if isinstance(inner, ast.Attribute) and inner.attr in {"parents", "parent"}:
                    return True
            if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div):
                # `destination = quarantine_base / stamp`. Derived when the left side is itself
                # a confined name, or is the producer's own resolved root.
                left = value.left
                if isinstance(left, ast.Name):
                    if left.id == "quarantine_base" and _quarantine_base_is_confined(tree, source):
                        return True
                    if left.id in _resolved_root_names(tree):
                        return True
                    return _bound_to_derived_path(tree, left.id, source, seen)
                return _expression_is_derived(tree, value, source, seen)
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                # `target = something.parent`: derived from a name held at the root of the tree
                # this producer walks, so `target.parent` is that tree, not a new destination.
                holder = value.func.value
                if isinstance(holder, ast.Name) and holder.id in _resolved_root_names(tree):
                    return True
    return False


def _executed_by_producer(node: ast.Call, tree: ast.AST, source: str) -> bool:
    """True when this call runs in the producer's own code, not in an imported helper.

    A destination is a property of the producer only if the producer itself reaches the write.
    A write inside ``runtime.confined_output`` (or any other imported module) cannot be
    attributed here; the helper enforces its own containment at write time instead.
    """
    from .effect_surface import _call_name

    if _call_name(node).rsplit(".", 1)[-1] == "publish_json":
        return True
    # A call is the producer's own when it is not `module.function(...)` where `module` is an
    # imported runtime module. Writes reached through an import are the helper's business.
    func = node.func
    if isinstance(func, ast.Attribute):
        root_name = func.value
        while isinstance(root_name, ast.Attribute):
            root_name = root_name.value
        if isinstance(root_name, ast.Name) and f"import {root_name.id}" in source:
            return False
    return True


def _confinement_symbol(tree: ast.AST, source: str) -> str | None:
    """Name of the root symbol a producer binds for confined publication, if any."""
    if "confined_output" not in source:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        from .effect_surface import _call_name

        if _call_name(node).rsplit(".", 1)[-1] != "publish_json" or len(node.args) < 1:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name):
            return first.id
        if isinstance(first, ast.Call) and _call_name(first).endswith("resolve"):
            return "path-root"
    return None


def _granted_destination(grants: Mapping[str, Any], destination: str, now_utc: str) -> bool:
    """True when an active, unexpired grant root strictly contains `destination`.

    The destination text comes from source, so it carries quotes (`'build/x'`) and sometimes a
    constructor (`Path('build/x')`). Every quoted literal it contains must be contained; if it
    names none, the text itself is used.
    """
    roots = grants.get("roots") or {}
    if destination == UNRESOLVED_RELATIVE:
        return False
    if destination == CONFINED_DESTINATION:
        # The producer's own helper confines this to the repository root and refuses the root
        # itself, traversal, and symlinks. It is admissible only when a root record exists.
        return bool(roots)
    literals = re.findall(r"'([^']*)'|\"([^\"]*)\"", destination)
    candidates = [first or second for first, second in literals] or [destination]
    for grant in grants.get("grants") or []:
        if grant.get("status") != "active":
            continue
        expires = grant.get("expires_utc")
        if expires and now_utc > str(expires):
            continue
        root_name = str(grant.get("root") or "")
        if root_name not in roots:
            continue
        if all(
            output_roots.contained_in(
                output_roots._normalize(root_name), output_roots._normalize(candidate)
            )
            for candidate in candidates
        ):
            return True
    return False


def output_root_verdict(
    root: Path, relative: str, effects: tuple[str, ...], *, now_utc: str = "9999-12-31T23:59:59Z"
) -> Mapping[str, str] | None:
    """Resolve a producer only when its write behaviour is established.

    Two independent sources, both required:

    * **observed** — a sandbox record shows every file the producer created stayed inside the
      confined tree for that mode (`docs/repair/evidence/px-os-1067-sandbox-evidence.json`);
    * **static** — the source has no caller-selected destination that bypasses the bound root.

    Static extraction alone was repeatedly wrong about these producers (it followed variable
    spellings rather than behaviour), so observation is the primary evidence and a producer
    with no observation is never resolved by this path.
    """
    if not effects or any(effect != "filesystem_mutation" for effect in effects):
        # Process, network and mixed producers are not this contract's business.
        return None
    grants = load_grants(root)
    if not grants.get("grants"):
        return None
    destinations = produced_destinations(root, relative)
    if not destinations:
        return None
    if not all(_granted_destination(grants, destination, now_utc) for destination in destinations):
        return None
    # Observation is required for every producer on this path. A static binding chain is an
    # interpretation; only a run shows where the bytes went. Dropping this for "simple" cases
    # is exactly how a check stops meaning anything.
    if not _observed_confined(root, relative, now_utc):
        return None
    return {"classification": "exempt", "reason": "authorized_output_root"}


def _observed_confined(root: Path, relative: str, now_utc: str) -> bool:
    """True when a retained sandbox run observed this producer staying inside its tree."""
    import hashlib

    evidence = Path(root) / SANDBOX_EVIDENCE_RELATIVE
    if not evidence.is_file():
        return False
    try:
        document = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    source = Path(root) / relative
    if not source.is_file():
        return False
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    for case in document.get("cases") or []:
        if case.get("producer") != relative:
            continue
        if case.get("observed_source_sha256") != digest:
            # The observation is about different bytes; it proves nothing about this source.
            continue
        if case.get("observed_confined") is not True:
            continue
        if case.get("escaping_paths"):
            continue
        return True
    return False
