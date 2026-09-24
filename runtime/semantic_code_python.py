"""Deterministic Python semantic analysis using only the standard-library AST.

This is a safe baseline backend, not a substitute for an external language server.
It provides useful structure even when pyright/jedi/etc. are unavailable and gives
Wave 2 an evidence source to compare external language-service answers against.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any

from .semantic_code_backend import SemanticBackend
from .semantic_code_document import DocumentSnapshot
from .semantic_code_types import (
    DiagnosticRecord,
    DiagnosticSeverity,
    ImportRecord,
    Position,
    ReferenceRecord,
    SemanticDocument,
    SymbolKind,
    SymbolRecord,
    TextRange,
    stable_id,
)


def _module_name(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or path.stem


def _char_column(snapshot: DocumentSnapshot, one_based_line: int, byte_column: int) -> int:
    line = snapshot.line_text(one_based_line - 1)
    raw = line.encode("utf-8")
    bounded = raw[:byte_column]
    try:
        return len(bounded.decode("utf-8"))
    except UnicodeDecodeError:
        return len(bounded.decode("utf-8", errors="ignore"))


def _position(snapshot: DocumentSnapshot, line: int, byte_column: int) -> Position:
    return Position(line - 1, _char_column(snapshot, line, byte_column))


def _node_range(snapshot: DocumentSnapshot, node: ast.AST) -> TextRange:
    line = int(getattr(node, "lineno", 1))
    col = int(getattr(node, "col_offset", 0))
    end_line = int(getattr(node, "end_lineno", line))
    end_col = int(getattr(node, "end_col_offset", col))
    return TextRange(
        _position(snapshot, line, col),
        _position(snapshot, end_line, end_col),
    )


def _definition_range(snapshot: DocumentSnapshot, node: ast.AST) -> TextRange:
    decorators = getattr(node, "decorator_list", ())
    if decorators:
        first = min(decorators, key=lambda item: (item.lineno, item.col_offset))
        body = _node_range(snapshot, node)
        decorator_start = _node_range(snapshot, first).start
        # AST decorator expressions begin after the @ token. Preserve indentation
        # while including @ so a definition replacement cannot strand it.
        decorator_start = Position(decorator_start.line, max(0, decorator_start.column - 1))
        return TextRange(decorator_start, body.end)
    return _node_range(snapshot, node)


def _syntax_diagnostic(snapshot: DocumentSnapshot, error: SyntaxError) -> DiagnosticRecord:
    line = max(0, (error.lineno or 1) - 1)
    col = max(0, (error.offset or 1) - 1)
    end_line = max(line, (getattr(error, "end_lineno", None) or error.lineno or 1) - 1)
    end_col = max(col + 1, (getattr(error, "end_offset", None) or error.offset or 1) - 1)
    location = TextRange(Position(line, col), Position(end_line, end_col))
    return DiagnosticRecord(
        diagnostic_id=stable_id(
            "diag", snapshot.relative_path, "python-ast", line, col, error.msg
        ),
        relative_path=snapshot.relative_path,
        severity=DiagnosticSeverity.ERROR,
        message=error.msg,
        location=location,
        source="python-ast",
        code="syntax-error",
    )


def _attribute_name(node: ast.Attribute) -> str:
    parts = [node.attr]
    value: ast.AST = node.value
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _decorator_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args: list[str] = []
    for arg in (*node.args.posonlyargs, *node.args.args):
        args.append(arg.arg)
    if node.args.vararg is not None:
        args.append("*" + node.args.vararg.arg)
    elif node.args.kwonlyargs:
        args.append("*")
    for arg in node.args.kwonlyargs:
        args.append(arg.arg)
    if node.args.kwarg is not None:
        args.append("**" + node.args.kwarg.arg)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(args)})"


class _Scanner(ast.NodeVisitor):
    def __init__(self, snapshot: DocumentSnapshot):
        self.snapshot = snapshot
        self.module_name = _module_name(snapshot.relative_path)
        self.symbols: list[SymbolRecord] = []
        self.references: list[ReferenceRecord] = []
        self.imports: list[ImportRecord] = []
        self._symbol_stack: list[SymbolRecord] = []
        self._qual_stack: list[str] = []
        self._ordinals: defaultdict[tuple[str, SymbolKind], int] = defaultdict(int)
        whole = TextRange(Position(0, 0), Position(snapshot.line_count - 1, len(snapshot.line_text(snapshot.line_count - 1))))
        module_id = stable_id("sym", snapshot.relative_path, "module", self.module_name, 0)
        module = SymbolRecord(
            symbol_id=module_id,
            name=self.module_name.rsplit(".", 1)[-1],
            qualified_name=self.module_name,
            kind=SymbolKind.MODULE,
            relative_path=snapshot.relative_path,
            declaration=whole,
            body=whole,
            language="python",
        )
        self.symbols.append(module)
        self._symbol_stack.append(module)

    @property
    def current_symbol(self) -> SymbolRecord:
        return self._symbol_stack[-1]

    def _qualified(self, name: str) -> str:
        return ".".join([self.module_name, *self._qual_stack, name])

    def _kind_for_function(self) -> SymbolKind:
        if self._symbol_stack and self._symbol_stack[-1].kind == SymbolKind.CLASS:
            return SymbolKind.METHOD
        return SymbolKind.FUNCTION

    def _add_symbol(
        self,
        node: ast.AST,
        *,
        name: str,
        kind: SymbolKind,
        signature: str | None = None,
        decorators: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> SymbolRecord:
        qualified = self._qualified(name)
        key = (qualified, kind)
        ordinal = self._ordinals[key]
        self._ordinals[key] += 1
        symbol = SymbolRecord(
            symbol_id=stable_id(
                "sym", self.snapshot.relative_path, kind.value, qualified, ordinal
            ),
            name=name,
            qualified_name=qualified,
            kind=kind,
            relative_path=self.snapshot.relative_path,
            declaration=_node_range(self.snapshot, node),
            body=_definition_range(self.snapshot, node),
            parent_symbol_id=self.current_symbol.symbol_id,
            language="python",
            signature=signature,
            decorators=decorators,
            metadata={"ordinal": ordinal, **(metadata or {})},
        )
        self.symbols.append(symbol)
        return symbol

    def _visit_definition(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = self._kind_for_function()
        decorators = tuple(_decorator_text(item) for item in node.decorator_list)
        if kind == SymbolKind.METHOD and any(
            name in {"property", "cached_property"}
            for name in decorators
        ):
            kind = SymbolKind.PROPERTY
        symbol = self._add_symbol(
            node,
            name=node.name,
            kind=kind,
            signature=_function_signature(node),
            decorators=decorators,
            metadata={"async": isinstance(node, ast.AsyncFunctionDef)},
        )
        self._symbol_stack.append(symbol)
        self._qual_stack.append(node.name)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        for decorator in node.decorator_list:
            self.visit(decorator)
        if node.returns is not None:
            self.visit(node.returns)
        for statement in node.body:
            self.visit(statement)
        self._qual_stack.pop()
        self._symbol_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_definition(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_definition(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        symbol = self._add_symbol(
            node,
            name=node.name,
            kind=SymbolKind.CLASS,
            decorators=tuple(_decorator_text(item) for item in node.decorator_list),
            metadata={"bases": tuple(_decorator_text(item) for item in node.bases)},
        )
        for base in node.bases:
            self.visit(base)
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._symbol_stack.append(symbol)
        self._qual_stack.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self._qual_stack.pop()
        self._symbol_stack.pop()

    def _assignment_names(self, target: ast.AST) -> list[tuple[str, ast.AST]]:
        if isinstance(target, ast.Name):
            return [(target.id, target)]
        if isinstance(target, (ast.Tuple, ast.List)):
            result: list[tuple[str, ast.AST]] = []
            for item in target.elts:
                result.extend(self._assignment_names(item))
            return result
        return []

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.current_symbol.kind in {SymbolKind.MODULE, SymbolKind.CLASS}:
            for target in node.targets:
                for name, name_node in self._assignment_names(target):
                    kind = SymbolKind.CONSTANT if name.isupper() else SymbolKind.VARIABLE
                    self._add_symbol(name_node, name=name, kind=kind)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self.current_symbol.kind in {SymbolKind.MODULE, SymbolKind.CLASS}:
            for name, name_node in self._assignment_names(node.target):
                kind = SymbolKind.CONSTANT if name.isupper() else SymbolKind.VARIABLE
                self._add_symbol(name_node, name=name, kind=kind)
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)

    def visit_Import(self, node: ast.Import) -> None:
        location = _node_range(self.snapshot, node)
        for alias in node.names:
            self.imports.append(
                ImportRecord(
                    relative_path=self.snapshot.relative_path,
                    module=alias.name,
                    imported_name=None,
                    alias=alias.asname,
                    location=location,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        location = _node_range(self.snapshot, node)
        module = node.module or ""
        for alias in node.names:
            self.imports.append(
                ImportRecord(
                    relative_path=self.snapshot.relative_path,
                    module=module,
                    imported_name=alias.name,
                    alias=alias.asname,
                    location=location,
                    level=node.level,
                )
            )

    def _add_reference(self, node: ast.AST, name: str, kind: str) -> None:
        location = _node_range(self.snapshot, node)
        source = self.current_symbol.symbol_id if self._symbol_stack else None
        self.references.append(
            ReferenceRecord(
                reference_id=stable_id(
                    "ref",
                    self.snapshot.relative_path,
                    location.start.line,
                    location.start.column,
                    name,
                    kind,
                ),
                name=name,
                relative_path=self.snapshot.relative_path,
                location=location,
                source_symbol_id=source,
                language="python",
                metadata={"syntax_kind": kind},
            )
        )

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._add_reference(node, node.id, "name")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            self._add_reference(node, _attribute_name(node), "attribute")
        # Visit the base but not the attribute token a second time.
        self.visit(node.value)


class PythonAstSemanticBackend(SemanticBackend):
    key = "python-ast"
    language = "python"
    suffixes = (".py", ".pyi")

    def analyze(self, snapshot: DocumentSnapshot) -> SemanticDocument:
        try:
            tree = ast.parse(snapshot.text, filename=snapshot.relative_path, type_comments=True)
        except SyntaxError as error:
            return SemanticDocument(
                relative_path=snapshot.relative_path,
                language=self.language,
                sha256=snapshot.raw_sha256,
                size_bytes=snapshot.size_bytes,
                diagnostics=(_syntax_diagnostic(snapshot, error),),
            )
        scanner = _Scanner(snapshot)
        scanner.visit(tree)
        symbols = tuple(sorted(scanner.symbols, key=lambda item: (
            item.declaration.start.line,
            item.declaration.start.column,
            item.qualified_name,
            item.symbol_id,
        )))
        references = tuple(sorted(scanner.references, key=lambda item: (
            item.location.start.line,
            item.location.start.column,
            item.name,
            item.reference_id,
        )))
        imports = tuple(sorted(scanner.imports, key=lambda item: (
            item.location.start.line,
            item.module,
            item.imported_name or "",
        )))
        return SemanticDocument(
            relative_path=snapshot.relative_path,
            language=self.language,
            sha256=snapshot.raw_sha256,
            size_bytes=snapshot.size_bytes,
            symbols=symbols,
            references=references,
            imports=imports,
        )
