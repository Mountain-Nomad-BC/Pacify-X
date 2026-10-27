"""Compare observed generation bindings; projection JSON cannot grant freshness."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .context_generation import ContextGenerationVector, _text, EXECUTION_LINEAGE_COMPONENTS

SCHEMA_VERSION = "px.projection-status/1.0"
PROTECTED_COMPONENTS = frozenset({"authority_revision", "policy_revision", "runtime_epoch", "execution_graph_revision", *EXECUTION_LINEAGE_COMPONENTS})
EXECUTION_COMPONENTS = {"authority_revision", "policy_revision", "runtime_epoch", "execution_graph_revision", "source_revision"}


@dataclass(frozen=True, slots=True)
class ProjectionReadPolicy:
    """Trusted host read policy, never reconstructed from projection state."""
    authority: str
    allow_degraded: bool = False

    def __post_init__(self):
        _text(self.authority, "projection policy authority")
        if type(self.allow_degraded) is not bool:
            raise ValueError("allow_degraded must be boolean")


@dataclass(frozen=True, slots=True)
class ProjectionStatus:
    projection_id: str
    state: str
    reasons: tuple[str, ...]
    stale_dependencies: tuple[str, ...]
    serve_allowed: bool
    rebuild_required: bool
    recorded_vector_sha256: str
    current_vector_sha256: str
    purpose: str
    policy_authority: str | None

    def as_mapping(self) -> dict:
        return {"schema_version": SCHEMA_VERSION,
                **{name: getattr(self, name) for name in self.__dataclass_fields__
                   if name not in {"reasons", "stale_dependencies"}},
                "reasons": list(self.reasons), "stale_dependencies": list(self.stale_dependencies)}


def evaluate_projection(projection_id: str, recorded: ContextGenerationVector,
                        current: ContextGenerationVector, *,
                        policy: ProjectionReadPolicy | None = None,
                        purpose: str = "read_only") -> ProjectionStatus:
    _text(projection_id, "projection_id")
    if not isinstance(recorded, ContextGenerationVector) or not isinstance(current, ContextGenerationVector):
        raise ValueError("projection comparison requires observed typed vectors")
    if (recorded.project_id, recorded.scope) != (current.project_id, current.scope):
        raise ValueError("projection project/scope mismatch")
    if purpose not in {"read_only", "execute"}:
        raise ValueError("unknown projection consumer purpose")
    if policy is not None and not isinstance(policy, ProjectionReadPolicy):
        raise ValueError("projection read policy requires trusted host authority")
    previous, observed = recorded.components, current.components
    changed = {name for name in set(previous) | set(observed) if previous.get(name) != observed.get(name)}
    required = set(recorded.required_components) | set(current.required_components)
    if purpose == "execute":
        required.update(EXECUTION_COMPONENTS)
        if set(previous).intersection(EXECUTION_LINEAGE_COMPONENTS) or set(observed).intersection(EXECUTION_LINEAGE_COMPONENTS):
            required.update(EXECUTION_LINEAGE_COMPONENTS)
    missing = {name for name in required if previous.get(name) is None or observed.get(name) is None}
    requirements_changed = (recorded.required_components != current.required_components or set(previous) != set(observed))
    reasons = tuple(["revision_drift:" + name for name in sorted(changed)]
                    + ["unavailable_required_dependency:" + name for name in sorted(missing)]
                    + (["required_component_contract_changed"] if requirements_changed else []))
    stale = tuple(sorted(changed | missing))
    state, allowed = "fresh", True
    if changed or missing or requirements_changed:
        allow_read = (policy is not None and policy.allow_degraded and purpose == "read_only"
                      and not missing and not requirements_changed and not changed.intersection(PROTECTED_COMPONENTS))
        state, allowed = ("degraded", True) if allow_read else ("blocked", False)
    return ProjectionStatus(projection_id, state, reasons, stale, allowed, state != "fresh",
                            recorded.vector_sha256, current.vector_sha256, purpose,
                            policy.authority if policy else None)


# ---------------------------------------------------------------------------
# Universal reach over registered projections (SEM-005).
#
# ``evaluate_projection`` compares two vectors for ONE projection. That is not
# enough: it only protects a projection that already opted in. Five
# authority-bearing projections are registered in
# registry/projection_dependencies.json, and before this existed none of them
# carried a generation vector, so a stale catalog could still be served as
# fresh. Opt-in coverage is not coverage.
#
# The gate below therefore enumerates the REGISTERED projections and refuses to
# call the gate satisfied while any authority-bearing one is ungated. An
# ungated projection is reported as blocked, never as fresh, because the
# honest state of an unmeasured projection is unknown.
# ---------------------------------------------------------------------------

GATED = "gated"
UNGATED = "ungated"


@dataclass(frozen=True, slots=True)
class RegisteredProjection:
    """A projection as its registry declares it."""

    projection_id: str
    output: str
    owner: str
    output_revision: str
    recorded_vector: ContextGenerationVector | None = None

    def __post_init__(self) -> None:
        _text(self.projection_id, "registered projection_id")
        _text(self.output, "registered projection output")
        _text(self.owner, "registered projection owner")
        _text(self.output_revision, "registered projection output_revision")
        if self.recorded_vector is not None and not isinstance(
            self.recorded_vector, ContextGenerationVector
        ):
            raise ValueError("registered projection vector must be a typed vector")


@dataclass(frozen=True, slots=True)
class UniversalGateReport:
    """Whether one gate covers every authority-bearing derived state."""

    complete: bool
    gated: tuple[str, ...]
    ungated: tuple[str, ...]
    statuses: Mapping[str, ProjectionStatus]

    def as_mapping(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "complete": self.complete,
            "gated": list(self.gated),
            "ungated": list(self.ungated),
            "statuses": {
                projection_id: status.as_mapping()
                for projection_id, status in sorted(self.statuses.items())
            },
        }


def evaluate_registered_projections(
    projections: Iterable[RegisteredProjection],
    current_vectors: Mapping[str, ContextGenerationVector],
    *,
    policy: ProjectionReadPolicy | None = None,
    purpose: str = "read_only",
) -> UniversalGateReport:
    """Gate every registered projection, and report any that are ungated.

    A projection with no recorded vector is reported as ``ungated`` and makes
    the report incomplete. It is NOT treated as fresh: an unmeasured projection
    is unknown, and reporting unknown as fresh is the exact failure this gate
    exists to prevent.
    """
    if not isinstance(current_vectors, Mapping):
        raise ValueError("universal gate requires a mapping of current vectors")

    gated: list[str] = []
    ungated: list[str] = []
    statuses: dict[str, ProjectionStatus] = {}

    for projection in sorted(projections, key=lambda item: item.projection_id):
        if not isinstance(projection, RegisteredProjection):
            raise ValueError("universal gate accepts only registered projections")
        if projection.recorded_vector is None or projection.projection_id not in current_vectors:
            ungated.append(projection.projection_id)
            statuses[projection.projection_id] = ProjectionStatus(
                projection.projection_id, UNGATED,
                ("no_recorded_generation_vector",), (), False, True,
                "", "", purpose, policy.authority if policy else None,
            )
            continue
        status = evaluate_projection(
            projection.projection_id, projection.recorded_vector,
            current_vectors[projection.projection_id], policy=policy, purpose=purpose,
        )
        statuses[projection.projection_id] = status
        gated.append(projection.projection_id)

    return UniversalGateReport(
        complete=not ungated, gated=tuple(gated), ungated=tuple(ungated),
        statuses=statuses,
    )


def assert_gate_complete(report: UniversalGateReport) -> None:
    """Fail closed unless one gate covers every registered projection."""
    if not report.complete:
        raise ValueError(
            "universal projection gate is incomplete; ungated projections: "
            + ", ".join(report.ungated)
        )
