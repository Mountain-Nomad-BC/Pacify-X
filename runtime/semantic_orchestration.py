"""Bounded read-only semantic orchestration over explicit project evidence sources."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .semantic_authorization import require_authorized
from .semantic_code_types import stable_id
from .semantic_cross_project import CrossProjectSemanticService
from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import QueryAuthorization, SemanticEvidence
from .semantic_model_context import materialize_model_context
from .semantic_project_map_bridge import query_project_map_evidence
from .semantic_query_receipts import query_receipt
from .semantic_retrieval_fusion import fuse_evidence


class SemanticReadOrchestrator:
    """Assemble model-ready read context without acquiring mutation authority."""

    def __init__(
        self,
        cross_project: CrossProjectSemanticService,
        *,
        limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
    ) -> None:
        if not isinstance(cross_project, CrossProjectSemanticService):
            raise TypeError("cross_project must be a CrossProjectSemanticService")
        self.cross_project = cross_project
        self.limits = limits

    def query(
        self,
        auth: QueryAuthorization,
        project_id: str,
        query: str,
        *,
        include_project_map: bool = True,
        max_results: int = 8,
    ) -> dict[str, object]:
        if type(query) is not str or not query.strip() or len(query.encode("utf-8")) > self.limits.max_query_bytes:
            raise ValueError("query must be nonempty and bounded")
        if type(include_project_map) is not bool:
            raise TypeError("include_project_map must be a boolean")
        if type(max_results) is not int or not 1 <= max_results <= self.limits.max_results:
            raise ValueError("max_results must be a positive integer within the result budget")

        required_operations = [
            "semantic.cross_project.query",
            "semantic.symbol.find",
            "semantic.knowledge.fuse",
            "semantic.model.context",
        ]
        if include_project_map:
            required_operations.append("semantic.project_map.query")
        # Validate every authority before invoking any project query so partial work does
        # not occur for a request that was never fully admitted.
        for operation in required_operations:
            require_authorized(auth, project_id, operation)

        semantic = self.cross_project.query(
            auth,
            project_id,
            "semantic.symbol.find",
            {
                "pattern": query,
                "substring": True,
                "case_sensitive": False,
                "max_results": max_results,
            },
        )
        descriptor = self.cross_project.catalog.get(project_id)
        evidence: list[SemanticEvidence] = []
        matches = semantic["result"].get("matches", [])
        if not isinstance(matches, list):
            raise RuntimeError("semantic symbol result matches must be a list")
        for item in matches:
            if not isinstance(item, dict):
                raise RuntimeError("semantic symbol matches must be objects")
            path = str(item.get("relative_path") or "")
            name = str(item.get("qualified_name") or item.get("name") or "symbol")
            evidence.append(
                SemanticEvidence(
                    source_id=stable_id(
                        "symbol-evidence",
                        project_id,
                        item.get("symbol_id"),
                        semantic["result"].get("project_revision"),
                    ),
                    source_kind="semantic_symbol",
                    title=name,
                    text=" ".join(
                        value
                        for value in (name, str(item.get("signature") or ""), path)
                        if value
                    ),
                    project_id=project_id,
                    lineage="runtime.semantic_code_service.SemanticCodeService.find_symbols",
                    locator=path,
                    revision=str(semantic["result"].get("project_revision") or "") or None,
                    trust=1.0,
                    structured={
                        "kind": item.get("kind"),
                        "symbol_id": item.get("symbol_id"),
                    },
                )
            )

        atlas_result: dict[str, object] | None = None
        if include_project_map:
            try:
                atlas_result, atlas_evidence = query_project_map_evidence(
                    project_id,
                    Path(descriptor.root),
                    query,
                    top_k=max_results,
                    limits=self.limits,
                )
                evidence.extend(atlas_evidence)
            except (FileNotFoundError, KeyError, OSError, ValueError) as exc:
                atlas_result = {
                    "valid": False,
                    "unknown": "project_map_unavailable_or_rejected",
                    "error_type": type(exc).__name__,
                }

        fused = fuse_evidence(
            query,
            project_id,
            tuple(evidence),
            identity_scope=("project", project_id),
            max_results=max_results,
            limits=self.limits,
        )
        context = materialize_model_context(fused, limits=self.limits)
        identity = {
            "semantic_revision": semantic["result"].get("project_revision"),
            "fused_receipt_sha256": fused.receipt_sha256,
            "context_item_count": context["item_count"],
            "context_byte_count": context["byte_count"],
            "project_map_valid": None if atlas_result is None else atlas_result.get("valid"),
        }
        receipt = query_receipt(
            operation="semantic.orchestrated.read",
            actor_id=auth.actor_id,
            project_id=project_id,
            authority_token_id=auth.token_id,
            request={
                "query": query,
                "include_project_map": include_project_map,
                "max_results": max_results,
            },
            result_identity=identity,
            limits=self.limits,
        )
        return {
            "project_id": project_id,
            "query": query,
            "semantic": semantic["result"],
            "project_map": atlas_result,
            "fused": asdict(fused),
            "model_context": context,
            "receipt": receipt,
            "effects": ["read"],
            "mutation": False,
            "authority_boundary": {
                "context_grants_execution": False,
                "context_grants_write": False,
                "follow_on_actions_require_px_contract": True,
            },
        }
