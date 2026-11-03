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
# A destination is the first positional or keyword argument of a write call, or the
# variable the call publishes from. Only purely syntactic facts are used.
_PATH_ARGUMENT_NAMES = frozenset(
    {"path", "dest", "destination", "target", "output", "out", "dst", "source", "src"}
)
_CONSTANT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def load_grants(root: Path) -> dict[str, Any]:
    path = Path(root) / GRANTS_RELATIVE
    if not path.is_file():
        return {"schema_version": output_roots.SCHEMA_VERSION, "roots": {}, "grants": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _argument_text(node: ast.Call) -> str | None:
    """Syntactic destination of a write call, or None when it cannot be determined.

    Only the receiver (`x.write_text(...)`) and arguments *named* like a path are used. The
    written content is never a destination: taking it made `Path('data.txt').write_text('x')`
    yield both the file and the payload, which then failed containment for the wrong reason.
    """
    parts: list[str] = []
    if isinstance(node.func, ast.Attribute):
        parts.append(ast.unparse(node.func.value))
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
    return " ".join(parts)


def produced_destinations(root: Path, relative: str) -> list[str]:
    """Constant path-like strings the producer may hand to a write call.

    Module-level and function-level string constants that look like paths are collected
    together with the write calls' argument text. Anything dynamic is reported by the
    absence of a constant, which fails the containment check — the fail-closed direction.
    """
    source = (Path(root) / relative).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    from .effect_surface import _call_name

    write_calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            leaf = name.rsplit(".", 1)[-1]
            if leaf in {"write_text", "write_bytes", "replace", "rename", "open", "mkdir"}:
                write_calls.add(node.lineno)

    destinations: list[str] = []
    for node in ast.walk(tree):
        # A module-level constant such as LEDGER_ROOT = "registry" is the clearest
        # statement of intent a static scan can get.
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and _CONSTANT_NAME.fullmatch(target.id) and target.id.isupper():
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    text = node.value.value
                    if text and not text.startswith(("http://", "https://")):
                        destinations.append(text)
        if isinstance(node, ast.Call) and node.lineno in write_calls:
            text = _argument_text(node)
            if text:
                destinations.append(text)
    return sorted(set(destinations))


def _granted_destination(grants: Mapping[str, Any], destination: str, now_utc: str) -> bool:
    """True when an active, unexpired grant root strictly contains `destination`.

    The destination text comes from source, so it carries quotes (`'build/x'`) and sometimes a
    constructor (`Path('build/x')`). Every quoted literal it contains must be contained; if it
    names none, the text itself is used.
    """
    roots = grants.get("roots") or {}
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
    """Resolve a producer only when every destination it writes lies under a grant."""
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
    return {"classification": "exempt", "reason": "authorized_output_root"}
