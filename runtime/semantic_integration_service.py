"""Top-level semantic integration facade with dependency-clean wave boundaries.

Wave 3 owns project registration, capability projection, and explicit read-only
cross-project semantic queries.  Wave 4 adds fused retrieval/model-context and memory
helpers.  Wave-4 helpers remain lazily imported so the service also preserves the
dependency-clean behavior of a Wave-3-only installation.
"""
from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any, Mapping

from .semantic_capability_projection import project_capabilities
from .semantic_cross_project import CrossProjectSemanticService
from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_registry import integration_inventory
from .semantic_integration_types import QueryAuthorization
from .semantic_project_catalog import SemanticProjectCatalog


class SemanticIntegrationService:
    """Governed facade over semantic integration surfaces.

    Installing this facade does not grant model or client authority.  Callers still need
    explicit :class:`QueryAuthorization` for each project/operation, and later Wave-4
    capabilities remain unavailable until their modules are actually installed.
    """

    def __init__(self, *, limits: SemanticIntegrationLimits = SemanticIntegrationLimits(), semantic_map_provider=None):
        self.limits = limits
        self.catalog = SemanticProjectCatalog(limits=limits)
        self.cross_project = CrossProjectSemanticService(self.catalog, limits=limits)
        self._orchestrator: object | None = None
        if semantic_map_provider is not None and not callable(semantic_map_provider):
            raise TypeError("semantic_map_provider must be callable")
        self.semantic_map_provider = semantic_map_provider

    def register_project(
        self,
        project_id: str,
        root: Path,
        *,
        labels: tuple[str, ...] = (),
    ):
        return self.catalog.register(project_id, root, read_only=True, labels=labels)

    def projection(self, context: str, modes: tuple[str, ...] = ()):
        return project_capabilities(context, modes, limits=self.limits)

    def query_operation(
        self,
        auth: QueryAuthorization,
        project_id: str,
        operation: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        """Execute one explicitly named Wave-1 semantic read through Wave-3 auth."""
        return self.cross_project.query(auth, project_id, operation, arguments)

    def _wave4_orchestrator(self):
        if self._orchestrator is None:
            try:
                module = import_module("runtime.semantic_orchestration")
            except ModuleNotFoundError as exc:
                if exc.name == "runtime.semantic_orchestration":
                    raise RuntimeError(
                        "orchestrated semantic retrieval requires Wave 4"
                    ) from exc
                raise
            self._orchestrator = module.SemanticReadOrchestrator(
                self.cross_project, limits=self.limits, semantic_map_provider=self.semantic_map_provider
            )
        return self._orchestrator

    def query(
        self,
        auth: QueryAuthorization,
        project_id: str,
        query: str,
        *,
        include_project_map: bool = True,
        max_results: int = 8,
        tie_subjects: tuple[dict[str, str], ...] = (),
    ) -> dict[str, object]:
        """Run the fused semantic read once the Wave-4 orchestrator is installed."""
        return self._wave4_orchestrator().query(
            auth,
            project_id,
            query,
            include_project_map=include_project_map,
            max_results=max_results,
            tie_subjects=tie_subjects,
        )

    def local_model_context(
        self, query_result: dict[str, object], *, max_bytes: int = 32768
    ) -> dict[str, object]:
        try:
            bridge = import_module("runtime.semantic_local_model_bridge")
        except ModuleNotFoundError as exc:
            if exc.name == "runtime.semantic_local_model_bridge":
                raise RuntimeError("local-model context requires Wave 4") from exc
            raise
        from .semantic_integration_types import FusedQueryResult

        fused_raw = query_result.get("fused")
        if not isinstance(fused_raw, dict):
            raise ValueError("query_result.fused must be an object")
        fused = FusedQueryResult(**fused_raw)
        return bridge.local_model_context(
            fused, max_bytes=max_bytes, limits=self.limits
        )

    def memory_integrity(self, contents, locations, *, project_id: str | None = None):
        try:
            bridge = import_module("runtime.semantic_memory_integrity")
        except ModuleNotFoundError as exc:
            if exc.name == "runtime.semantic_memory_integrity":
                raise RuntimeError("memory integrity requires Wave 4") from exc
            raise
        return bridge.validate_memory_references(
            contents,
            locations,
            project_id=project_id,
            max_references=self.limits.max_memory_references,
        )

    def inventory(self) -> dict[str, object]:
        return integration_inventory()

    def plan_remap(self, auth, project_id, requests, *, allowed_roots, max_windows_path=240):
        from .semantic_authorization import require_authorized
        from .semantic_entity import EntityRegistry
        from .semantic_locator import LocatorRegistry
        from .semantic_migration import plan_remap
        from .librarian_semantic_map import load_semantic_map, SemanticMap
        require_authorized(auth, project_id, "semantic.remap.plan")
        root = Path(self.catalog.get(project_id).root)
        owner = self.semantic_map_provider(project_id, root) if self.semantic_map_provider else load_semantic_map(root)
        if type(owner) is not SemanticMap:
            raise TypeError("remap requires the canonical semantic map owner")
        owner.assert_current()
        entities = EntityRegistry.from_snapshot_bytes(owner.entity_snapshot_bytes)
        locators = LocatorRegistry.from_snapshot_bytes(entities, owner.locator_snapshot_bytes())
        return plan_remap(root, entities, locators, requests, compact_addresses=owner.compact_addresses,
                          allowed_roots=allowed_roots, max_windows_path=max_windows_path)

    def compile_remap(self, auth, project_id, proposal):
        from .semantic_authorization import require_authorized
        from .semantic_migration import compile_remap
        require_authorized(auth, project_id, "semantic.remap.compile")
        return compile_remap(Path(self.catalog.get(project_id).root), proposal)

    def close(self) -> None:
        self.cross_project.close()
