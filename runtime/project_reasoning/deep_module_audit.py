"""Produce deterministic interface-depth evidence for Python modules."""

from __future__ import annotations

import ast
from pathlib import Path


def inspect_python_module(path: Path, *, project_root: Path) -> dict[str, object]:
    root = project_root.resolve(strict=True)
    source = path.resolve(strict=True)
    try:
        relative = source.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(f"module path escapes project: {path}") from error
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=relative)
    rows = []
    for node in tree.body:
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ) or node.name.startswith("_"):
            continue
        if isinstance(node, ast.ClassDef):
            public = [
                item
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not item.name.startswith("_")
            ]
            interface_burden = sum(
                len(item.args.posonlyargs)
                + len(item.args.args)
                + len(item.args.kwonlyargs)
                + 1
                for item in public
            )
            implementation_nodes = sum(len(tuple(ast.walk(item))) for item in public)
            public_members = [item.name for item in public]
        else:
            interface_burden = (
                len(node.args.posonlyargs)
                + len(node.args.args)
                + len(node.args.kwonlyargs)
                + 1
            )
            implementation_nodes = len(tuple(ast.walk(node)))
            public_members = []
        depth = round(implementation_nodes / max(interface_burden, 1), 3)
        rows.append(
            {
                "symbol": node.name,
                "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                "line": node.lineno,
                "interface_burden": interface_burden,
                "implementation_nodes": implementation_nodes,
                "depth_proxy": depth,
                "public_members": public_members,
            }
        )
    rows.sort(key=lambda item: (item["line"], item["symbol"]))
    return {
        "valid": True,
        "path": relative,
        "symbol_count": len(rows),
        "symbols": rows,
        "metric_boundary": "AST proxy only; requires call-graph and change-history evidence before architectural action",
    }
