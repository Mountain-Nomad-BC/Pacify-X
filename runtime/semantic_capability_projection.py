"""Project semantic operations into client/context/mode surfaces without granting authority."""
from __future__ import annotations
from importlib.util import find_spec
from .semantic_context_profiles import context_profile
from .semantic_mode_profiles import validate_modes
from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import CapabilityProjection, IntegrationEffect, IntegrationOperation, projection_digest

_RISK = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}

# Wave-4 entries are declared here so installation of those modules automatically extends
# the projection without Wave 3 importing them or pretending they are currently usable.
_OPTIONAL_MODULES = {
    "semantic.knowledge.fuse": "runtime.semantic_retrieval_fusion",
    "semantic.memory.integrity": "runtime.semantic_memory_integrity",
    "semantic.memory.plan_relocation": "runtime.semantic_memory_relocation",
    "semantic.memory.apply_relocation": "runtime.semantic_memory_relocation",
    "semantic.model.context": "runtime.semantic_model_context",
}

OPERATIONS: tuple[IntegrationOperation, ...] = (
    IntegrationOperation("semantic.project.summary", (IntegrationEffect.READ,), "R0", "wave1", cross_project_allowed=True),
    IntegrationOperation("semantic.symbol.find", (IntegrationEffect.READ,), "R0", "wave1", cross_project_allowed=True),
    IntegrationOperation("semantic.symbol.overview", (IntegrationEffect.READ,), "R0", "wave1", cross_project_allowed=True),
    IntegrationOperation("semantic.reference.find", (IntegrationEffect.READ,), "R0", "wave1", cross_project_allowed=True),
    IntegrationOperation("semantic.diagnostics.file", (IntegrationEffect.READ,), "R0", "wave1", cross_project_allowed=True),
    IntegrationOperation("semantic.edit.plan_replace", (IntegrationEffect.PLAN,), "R1", "wave1"),
    IntegrationOperation("semantic.edit.plan_insert_before", (IntegrationEffect.PLAN,), "R1", "wave1"),
    IntegrationOperation("semantic.edit.plan_insert_after", (IntegrationEffect.PLAN,), "R1", "wave1"),
    IntegrationOperation("semantic.edit.preview", (IntegrationEffect.READ,), "R1", "wave1"),
    IntegrationOperation("semantic.edit.apply", (IntegrationEffect.WRITE,), "R3", "wave1", mutation=True),
    IntegrationOperation("lsp.document_symbols", (IntegrationEffect.READ, IntegrationEffect.PROCESS), "R1", "wave2", cross_project_allowed=True),
    IntegrationOperation("lsp.definition", (IntegrationEffect.READ, IntegrationEffect.PROCESS), "R1", "wave2", cross_project_allowed=True),
    IntegrationOperation("lsp.declaration", (IntegrationEffect.READ, IntegrationEffect.PROCESS), "R1", "wave2", cross_project_allowed=True),
    IntegrationOperation("lsp.implementation", (IntegrationEffect.READ, IntegrationEffect.PROCESS), "R1", "wave2", cross_project_allowed=True),
    IntegrationOperation("lsp.references", (IntegrationEffect.READ, IntegrationEffect.PROCESS), "R1", "wave2", cross_project_allowed=True),
    IntegrationOperation("lsp.rename", (IntegrationEffect.WRITE, IntegrationEffect.PROCESS), "R3", "wave2", mutation=True),
    IntegrationOperation("semantic.cross_project.query", (IntegrationEffect.READ,), "R0", "wave3", cross_project_allowed=True),
    IntegrationOperation("semantic.project_map.query", (IntegrationEffect.READ,), "R0", "wave3", cross_project_allowed=True),
    IntegrationOperation("semantic.authority.inspect", (IntegrationEffect.READ,), "R0", "wave3", cross_project_allowed=True),
    IntegrationOperation("semantic.evidence.bind", (IntegrationEffect.PLAN,), "R1", "wave3", cross_project_allowed=True),
    IntegrationOperation("semantic.knowledge.fuse", (IntegrationEffect.READ,), "R0", "wave4", cross_project_allowed=True),
    IntegrationOperation("semantic.memory.integrity", (IntegrationEffect.READ,), "R0", "wave4", cross_project_allowed=True),
    IntegrationOperation("semantic.memory.plan_relocation", (IntegrationEffect.PLAN,), "R1", "wave4"),
    IntegrationOperation("semantic.memory.apply_relocation", (IntegrationEffect.WRITE,), "R3", "wave4", mutation=True),
    IntegrationOperation("semantic.model.context", (IntegrationEffect.READ,), "R0", "wave4", cross_project_allowed=True),
)


def _operation_available(operation: IntegrationOperation) -> bool:
    module = _OPTIONAL_MODULES.get(operation.name)
    return module is None or find_spec(module) is not None


def operation_catalog(*, available_only: bool = False) -> dict[str, IntegrationOperation]:
    items = OPERATIONS if not available_only else tuple(op for op in OPERATIONS if _operation_available(op))
    return {item.name: item for item in items}


def project_capabilities(
    context_name: str,
    modes: tuple[str, ...] = (),
    *,
    limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
) -> CapabilityProjection:
    if type(modes) is not tuple:
        raise TypeError("modes must be a tuple")
    if len(modes) > limits.max_modes:
        raise ValueError("mode budget exceeded")
    context = context_profile(context_name)
    profiles = validate_modes(modes)
    permitted_effects = set(context.allowed_effects)
    if profiles:
        for profile in profiles:
            permitted_effects.intersection_update(profile.allowed_effects)
    excluded = {name for profile in profiles for name in profile.excluded_operations}
    required = {name for profile in profiles for name in profile.required_operations}
    cross_project_requested = "query-projects" in modes
    cross_project_exposed = context.cross_project and cross_project_requested
    operations: list[str] = []
    denied: list[tuple[str, str]] = []
    max_risk = _RISK.get(context.max_risk, -1)

    for op in OPERATIONS[:limits.max_operations]:
        reason = None
        if not _operation_available(op):
            reason = "integration_module_unavailable"
        elif op.name in excluded:
            reason = "excluded_by_mode"
        elif not set(op.effects).issubset(permitted_effects):
            reason = "effect_not_exposed"
        elif _RISK.get(op.risk, 99) > max_risk:
            reason = "risk_above_context_ceiling"
        elif op.name == "semantic.cross_project.query" and not cross_project_requested:
            reason = "query_projects_mode_required"
        elif op.name == "semantic.cross_project.query" and not cross_project_exposed:
            reason = "cross_project_not_exposed"
        if reason:
            denied.append((op.name, reason))
        else:
            operations.append(op.name)

    missing = required - set(operations)
    if missing:
        raise ValueError(f"mode requires unavailable operations: {sorted(missing)!r}")
    canonical_modes = tuple(sorted(modes))
    ops = tuple(sorted(operations))
    den = tuple(sorted(denied))
    return CapabilityProjection(
        context.name,
        canonical_modes,
        ops,
        den,
        projection_digest(context.name, canonical_modes, ops, den),
    )
