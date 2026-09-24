"""Prepare governed semantic context for the resident local PX operator model.

Context is data, not authority.  The tiny operator may invoke separately admitted PX
skills/workflows/contracts, but receiving this payload never grants a tool, write,
process, network, learning, graph, or memory mutation permission by itself.
"""
from __future__ import annotations

from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import FusedQueryResult
from .semantic_model_context import materialize_model_context


def local_model_context(
    result: FusedQueryResult,
    *,
    max_bytes: int = 32768,
    limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
) -> dict[str, object]:
    return materialize_model_context(
        result,
        max_bytes=max_bytes,
        limits=limits,
        annotations={
            "consumer_profile": "local-model",
            "operator_role": "librarian-concierge-grunt",
            "execution_authority": "not_granted_by_context",
            "tool_calls_allowed_by_context": False,
            "tool_authority_source": "separate_px_contracts",
            "learning_updates_require_contract": True,
            "graph_map_updates_require_contract": True,
            "purpose": "governed_operator_context",
        },
    )
