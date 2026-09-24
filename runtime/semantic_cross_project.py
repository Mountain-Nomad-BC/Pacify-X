"""Read-only cross-project semantic query facade."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .semantic_authorization import require_authorized
from .semantic_code_service import SemanticCodeService
from .semantic_code_types import canonical_json_bytes
from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import QueryAuthorization
from .semantic_project_catalog import SemanticProjectCatalog


_READ_OPERATIONS = frozenset(
    {
        "semantic.project.summary",
        "semantic.symbol.find",
        "semantic.symbol.overview",
        "semantic.reference.find",
        "semantic.diagnostics.file",
    }
)


def _bool_arg(args: Mapping[str, Any], name: str, default: bool) -> bool:
    value = args.get(name, default)
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _int_arg(
    args: Mapping[str, Any],
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int,
) -> int:
    value = args.get(name, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def _optional_text(args: Mapping[str, Any], name: str, *, max_bytes: int = 8192) -> str | None:
    value = args.get(name)
    if value is None:
        return None
    if type(value) is not str or len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} must be text bounded to {max_bytes} UTF-8 bytes")
    return value


def _text(args: Mapping[str, Any], name: str, *, max_bytes: int = 65536) -> str:
    value = args.get(name, "")
    if type(value) is not str or len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} must be text bounded to {max_bytes} UTF-8 bytes")
    return value


def _kinds(args: Mapping[str, Any]) -> tuple[str, ...]:
    value = args.get("kinds", ())
    if not isinstance(value, (list, tuple)) or len(value) > 32:
        raise ValueError("kinds must be a bounded list/tuple")
    kinds: list[str] = []
    for item in value:
        if type(item) is not str or not item or len(item.encode("utf-8")) > 64:
            raise ValueError("kinds entries must be bounded nonempty text")
        kinds.append(item)
    if len(set(kinds)) != len(kinds):
        raise ValueError("kinds entries must be unique")
    return tuple(kinds)


class CrossProjectSemanticService:
    """Execute explicit, authorized read operations against a registered project."""

    def __init__(
        self,
        catalog: SemanticProjectCatalog,
        *,
        semantic: SemanticCodeService | None = None,
        limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
    ):
        self.catalog = catalog
        self.semantic = semantic or SemanticCodeService(allow_writes=False)
        self.limits = limits

    def query(
        self,
        auth: QueryAuthorization,
        project_id: str,
        operation: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        if operation not in _READ_OPERATIONS:
            # Authorization is checked first so a caller cannot use the error surface to
            # probe unsupported operations it was never authorized to invoke.
            require_authorized(auth, project_id, operation)
            raise ValueError("unsupported cross-project semantic operation")
        require_authorized(auth, project_id, operation)
        if arguments is not None and not isinstance(arguments, Mapping):
            raise TypeError("arguments must be a mapping")
        args = dict(arguments or {})
        encoded = canonical_json_bytes(args)
        if len(encoded) > self.limits.max_query_bytes:
            raise ValueError("cross-project argument budget exceeded")

        with self.catalog.borrow(project_id) as descriptor:
            if not descriptor.read_only:
                raise PermissionError("cross-project semantic service requires read-only project registration")
            root = Path(descriptor.root)
            if operation == "semantic.project.summary":
                payload = self.semantic.project_summary(
                    root, refresh=_bool_arg(args, "refresh", False)
                )
            elif operation == "semantic.symbol.find":
                payload = self.semantic.find_symbols(
                    root,
                    _text(args, "pattern", max_bytes=self.limits.max_query_bytes),
                    relative_path=_optional_text(args, "relative_path"),
                    kinds=_kinds(args),
                    substring=_bool_arg(args, "substring", False),
                    case_sensitive=_bool_arg(args, "case_sensitive", True),
                    max_results=_int_arg(
                        args,
                        "max_results",
                        self.limits.max_results,
                        maximum=self.limits.max_results,
                    ),
                    refresh=_bool_arg(args, "refresh", False),
                )
            elif operation == "semantic.symbol.overview":
                payload = self.semantic.symbol_overview(
                    root,
                    _text(args, "relative_path", max_bytes=8192),
                    max_depth=_int_arg(args, "max_depth", 4, maximum=8),
                    max_results=_int_arg(
                        args,
                        "max_results",
                        self.limits.max_results,
                        maximum=self.limits.max_results,
                    ),
                )
            elif operation == "semantic.reference.find":
                payload = self.semantic.find_references(
                    root,
                    _text(args, "symbol_id", max_bytes=512),
                    max_results=_int_arg(
                        args,
                        "max_results",
                        self.limits.max_results,
                        maximum=self.limits.max_results,
                    ),
                )
            else:  # semantic.diagnostics.file
                payload = self.semantic.diagnostics(
                    root, relative_path=_optional_text(args, "relative_path")
                )

            return {
                "project_id": project_id,
                "read_only": True,
                "operation": operation,
                "result": payload,
            }

    def close(self) -> None:
        self.semantic.sessions.close_all()
