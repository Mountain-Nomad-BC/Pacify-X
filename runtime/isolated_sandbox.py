"""Isolated Agent Sandbox — the single coordinated execution mode.

The sandbox is **one mode**, not several independent toggles. Setting it to ``ON``
atomically establishes:

* monitoring of governed agent processes (activity, creation/termination,
  parent/child relationships, network connection attempts);
* stable process registration (PID + process-start identity, agent->run->process);
* Gremlin Nanny protection with a control plane that is **read-only to governed
  agents**;
* network policy enforcement with fail-closed behavior for governed external
  connectivity;
* enforcement rules (terminate/record on unauthorized external access where the
  policy says so);
* logging/run provenance recording the isolation state; and
* orchestrator awareness plus an external-information escalation boundary.

PX runtime policy is the authority that enforces the mode; a UI control only
selects it. This owner is the authority: it validates the mode, records it in run
provenance, and answers the enforcement questions the runtime and Gremlin ask.

Enforcement of network policy is *not* implemented here as a second monitor: the
mode configures the canonical Gremlin Nanny (see ``runtime.gremlin``), which owns
observation and enforcement. This owner produces the sandbox policy those controls
consume and the escalation record for external information.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Iterable, Mapping

from .contracts import validate_instance
from .json_io import bounded_canonical_json_bytes
from .paths import framework_root

SCHEMA_VERSION = "px.isolated-agent-sandbox/1.0"
CONTRACT_RELATIVE = "contracts/isolated-agent-sandbox.schema.json"

MODES = ("OFF", "ON")
MAX_SANDBOX_POLICY_BYTES = 262_144
SANDBOX_POLICY_RELATIVE = Path(
    ".agentic_engineering_os_px", "sandbox", "isolated-agent-sandbox.json"
)

# The components a coordinated activation must establish. Partial activation is a
# failure: the mode is atomic.
REQUIRED_COMPONENTS = (
    "monitoring",
    "process_registration",
    "gremlin_protection",
    "network_policy",
    "enforcement_rules",
    "logging_context",
    "orchestrator_awareness",
)


class SandboxPolicyError(ValueError):
    """Raised when the sandbox policy is invalid or activation is incomplete."""


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    default: str
    allowed_endpoints: tuple[str, ...] = ()
    terminate_on_unauthorized: bool = True

    def __post_init__(self) -> None:
        if self.default not in {"deny", "allow"}:
            raise SandboxPolicyError("network policy default must be deny or allow")
        if self.default == "allow":
            raise SandboxPolicyError(
                "sandbox network policy must default to deny for governed agents"
            )

    def permits(self, endpoint: str) -> bool:
        """Return True only for an explicitly authorized endpoint (fail closed)."""
        return endpoint in self.allowed_endpoints

    def as_dict(self) -> dict[str, Any]:
        return {
            "default": self.default,
            "allowed_endpoints": list(self.allowed_endpoints),
            "terminate_on_unauthorized": self.terminate_on_unauthorized,
        }


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    mode: str
    scope_key: str
    policy_revision: str
    network_policy: NetworkPolicy
    control_plane_read_only: bool = True
    require_process_identity: bool = True
    fail_closed: bool = True
    escalation_required: bool = True
    established_components: tuple[str, ...] = ()
    authority_granted: bool = False

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise SandboxPolicyError(f"unknown sandbox mode {self.mode!r}")
        if type(self.scope_key) is not str or not self.scope_key.strip():
            raise SandboxPolicyError("sandbox mode requires a workspace/session scope key")
        if type(self.policy_revision) is not str or not self.policy_revision.strip():
            raise SandboxPolicyError("sandbox mode requires a policy revision")
        if self.authority_granted is not False:
            raise SandboxPolicyError("sandbox policy never grants authority")
        if self.mode == "ON":
            missing = [name for name in REQUIRED_COMPONENTS if name not in self.established_components]
            if missing:
                raise SandboxPolicyError(
                    "sandbox mode ON requires every coordinated component: " + ",".join(missing)
                )
            if not self.fail_closed:
                raise SandboxPolicyError("sandbox mode ON must fail closed")
            if not self.control_plane_read_only:
                raise SandboxPolicyError("sandbox mode ON requires a read-only control plane")

    @property
    def active(self) -> bool:
        return self.mode == "ON"

    def as_dict(self) -> dict[str, Any]:
        body = {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "scope_key": self.scope_key,
            "policy_revision": self.policy_revision,
            "network_policy": self.network_policy.as_dict(),
            "control_plane_read_only": self.control_plane_read_only,
            "require_process_identity": self.require_process_identity,
            "fail_closed": self.fail_closed,
            "escalation_required": self.escalation_required,
            "established_components": list(self.established_components),
            "authority_granted": False,
        }
        return {**body, "policy_sha256": sandbox_policy_sha256(body)}


def sandbox_policy_sha256(body: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in body.items() if key != "policy_sha256"}
    return hashlib.sha256(bounded_canonical_json_bytes(payload, max_bytes=262_144)).hexdigest()


def sandbox_off(*, scope_key: str, policy_revision: str = "sandbox-r1") -> SandboxPolicy:
    return SandboxPolicy(
        mode="OFF",
        scope_key=scope_key,
        policy_revision=policy_revision,
        network_policy=NetworkPolicy(default="deny", allowed_endpoints=(), terminate_on_unauthorized=False),
    )


def full_component_acknowledgments() -> dict[str, bool]:
    """The trusted-host acknowledgment image for a fully installed sandbox."""
    return {name: True for name in REQUIRED_COMPONENTS}


def establish_sandbox(
    *,
    scope_key: str,
    allowed_endpoints: Iterable[str] = (),
    policy_revision: str = "sandbox-r1",
    terminate_on_unauthorized: bool = True,
    component_acknowledgments: Mapping[str, bool] | None = None,
) -> SandboxPolicy:
    """Atomically establish Isolated Agent Sandbox mode.

    Every coordinated component is marked established in the same policy image, so
    there is no window in which only part of the mode is active. Endpoints are
    normalized and de-duplicated; an endpoint with a scheme separator is rejected
    so an authorized endpoint cannot smuggle a broad host match.

    S01: a requested configuration is not an installed enforcement. Every
    required component must carry an explicit trusted-host acknowledgment;
    missing or false acknowledgments fail closed instead of claiming protected
    readiness.
    """
    acknowledgments = dict(component_acknowledgments or {})
    missing_acks = [
        name for name in REQUIRED_COMPONENTS if acknowledgments.get(name) is not True
    ]
    if missing_acks:
        raise SandboxPolicyError(
            "sandbox mode ON requires trusted-host acknowledgments for every "
            "component; not ready (fail closed): " + ",".join(missing_acks)
        )
    normalized: list[str] = []
    for endpoint in allowed_endpoints:
        value = str(endpoint).strip()
        if not value:
            raise SandboxPolicyError("allowed endpoint must be nonempty text")
        if value.startswith(("http://", "https://")) or "/" in value.rsplit(":", 1)[0]:
            raise SandboxPolicyError(
                f"allowed endpoint must be an exact host[:port], not a URL or path: {value!r}"
            )
        normalized.append(value)
    policy = SandboxPolicy(
        mode="ON",
        scope_key=scope_key,
        policy_revision=policy_revision,
        network_policy=NetworkPolicy(
            default="deny",
            allowed_endpoints=tuple(sorted(set(normalized))),
            terminate_on_unauthorized=terminate_on_unauthorized,
        ),
        established_components=REQUIRED_COMPONENTS,
    )
    return validate_sandbox_policy(policy)


def load_sandbox_policy(project_root: Path) -> SandboxPolicy | None:
    """Load and validate the exact workspace policy image, if one is persisted."""
    root = Path(project_root).resolve(strict=True)
    target = root / SANDBOX_POLICY_RELATIVE
    for candidate in (
        root / ".agentic_engineering_os_px",
        root / ".agentic_engineering_os_px" / "sandbox",
        target,
    ):
        if candidate.is_symlink():
            raise SandboxPolicyError("persisted sandbox policy path must not contain symlinks")
    if not target.exists():
        return None
    metadata = target.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_SANDBOX_POLICY_BYTES:
        raise SandboxPolicyError("persisted sandbox policy must be a bounded regular file")
    resolved_target = target.resolve(strict=True)
    try:
        resolved_target.relative_to(root)
    except ValueError as error:
        raise SandboxPolicyError("persisted sandbox policy escapes the project root") from error
    try:
        with target.open("rb") as stream:
            raw = stream.read(MAX_SANDBOX_POLICY_BYTES + 1)
        if len(raw) > MAX_SANDBOX_POLICY_BYTES:
            raise SandboxPolicyError("persisted sandbox policy exceeds its byte bound")
        value = json.loads(raw.decode("utf-8"))
    except SandboxPolicyError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SandboxPolicyError(f"persisted sandbox policy is unreadable: {error}") from error
    if type(value) is not dict:
        raise SandboxPolicyError("persisted sandbox policy must be a JSON object")
    policy = sandbox_policy_from_dict(value)
    if policy.scope_key != root.as_posix():
        raise SandboxPolicyError("persisted sandbox policy belongs to a different project scope")
    return policy


def validate_sandbox_policy(policy: SandboxPolicy) -> SandboxPolicy:
    contract = framework_root() / CONTRACT_RELATIVE
    validate_instance(policy.as_dict(), contract)
    return policy


def sandbox_policy_from_dict(value: Mapping[str, Any]) -> SandboxPolicy:
    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        raise SandboxPolicyError("typed isolated-agent-sandbox policy required")
    policy_fields = {
        "schema_version", "mode", "scope_key", "policy_revision", "network_policy",
        "control_plane_read_only", "require_process_identity", "fail_closed",
        "escalation_required", "established_components", "authority_granted",
        "policy_sha256",
    }
    if set(value) != policy_fields:
        raise SandboxPolicyError("sandbox policy fields do not match the canonical contract")
    if value.get("authority_granted") is not False:
        raise SandboxPolicyError("sandbox policy must not grant authority")
    network = value.get("network_policy")
    if not isinstance(network, Mapping) or set(network) != {
        "default", "allowed_endpoints", "terminate_on_unauthorized"
    }:
        raise SandboxPolicyError("sandbox policy requires a network policy")
    if type(network["allowed_endpoints"]) is not list or type(value["established_components"]) is not list:
        raise SandboxPolicyError("sandbox policy arrays must use canonical JSON arrays")
    policy = SandboxPolicy(
        mode=str(value["mode"]),
        scope_key=str(value["scope_key"]),
        policy_revision=str(value["policy_revision"]),
        network_policy=NetworkPolicy(
            default=str(network["default"]),
            allowed_endpoints=tuple(str(item) for item in network.get("allowed_endpoints", ())),
            terminate_on_unauthorized=bool(network.get("terminate_on_unauthorized", True)),
        ),
        control_plane_read_only=bool(value.get("control_plane_read_only", True)),
        require_process_identity=bool(value.get("require_process_identity", True)),
        fail_closed=bool(value.get("fail_closed", True)),
        escalation_required=bool(value.get("escalation_required", True)),
        established_components=tuple(str(item) for item in value.get("established_components", ())),
    )
    # Exact round-trip prevents omitted/extra fields and lossy coercions from
    # being accepted as the policy that was originally persisted.
    expected_image = policy.as_dict()
    if dict(value) != expected_image:
        raise SandboxPolicyError("sandbox policy image is not the canonical typed representation")
    expected = value.get("policy_sha256")
    if type(expected) is not str or expected != sandbox_policy_sha256(value):
        raise SandboxPolicyError("sandbox policy digest differs from its image")
    return policy


# ---------------------------------------------------------------------------
# Enforcement decisions: the questions runtime/Gremlin/orchestrator ask.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ConnectionDecision:
    endpoint: str
    permitted: bool
    enforcement_action: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


def decide_connection(policy: SandboxPolicy, endpoint: str, *, known_authorized: bool | None) -> ConnectionDecision:
    """Decide a governed agent's external connection under the sandbox.

    Fail closed (mode ON): an unknown authorization is a denial. ``known_authorized``
    is False/True only when the enforcement layer can *prove* authorization; ``None``
    ("unknown") is treated as a denial.
    """
    if not policy.active:
        return ConnectionDecision(endpoint, True, "none", "sandbox mode is off")
    if known_authorized is None:
        return ConnectionDecision(
            endpoint, False,
            "terminate_execution_tree" if policy.network_policy.terminate_on_unauthorized else "deny",
            "authorization could not be determined (fail closed)",
        )
    if known_authorized and policy.network_policy.permits(endpoint):
        return ConnectionDecision(endpoint, True, "none", "endpoint is explicitly authorized")
    return ConnectionDecision(
        endpoint, False,
        "terminate_execution_tree" if policy.network_policy.terminate_on_unauthorized else "deny",
        "endpoint is not in the sandbox allowlist",
    )


def control_plane_read_only_for_agents(policy: SandboxPolicy) -> bool:
    """While sandbox mode is ON, the containment control plane is read-only to agents."""
    return policy.active and policy.control_plane_read_only


def orchestrator_context(policy: SandboxPolicy) -> dict[str, Any]:
    """The explicit runtime context the orchestrating LLM must receive."""
    if not policy.active:
        return {
            "schema_version": SCHEMA_VERSION,
            "isolated_agent_sandbox": "OFF",
            "note": "Subordinate agents run under the normal PX execution environment.",
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "isolated_agent_sandbox": "ACTIVE",
        "subordinate_agents_cannot_retrieve_external_information": True,
        "network_policy": policy.network_policy.as_dict(),
        "approved_communication_mechanisms": [
            "workspace-orchestrator-mediated-external-retrieval",
            "explicitly-authorized-endpoint",
        ],
        "external_information_escalation_procedure": (
            "Direct an isolated agent to raise an external-information request; the "
            "workspace orchestrator retrieves it through an approved mechanism and "
            "returns only the sanitized result."
        ),
        "consequence_of_unauthorized_connection": (
            "terminate_execution_tree" if policy.network_policy.terminate_on_unauthorized
            else "connection denied"
        ),
        "policy_revision": policy.policy_revision,
        "scope_key": policy.scope_key,
    }


def sandbox_provenance(policy: SandboxPolicy, *, run_id: str, agent_id: str, process_identity: str) -> dict[str, Any]:
    """Run/session provenance recording the isolation state for logging."""
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "agent_id": agent_id,
        "process_identity": process_identity,
        "isolated_agent_sandbox": policy.mode,
        "policy_revision": policy.policy_revision,
        "scope_key": policy.scope_key,
        "policy_sha256": policy.as_dict()["policy_sha256"],
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# External information escalation boundary
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EscalationRequest:
    escalation_id: str
    agent_execution_id: str
    requested_information: str
    reason: str
    raised_at_utc: str

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


@dataclass(frozen=True, slots=True)
class EscalationResult:
    escalation_id: str
    disposition: str
    sanitized_result: str | None
    mediator: str
    resolved_at_utc: str

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


class EscalationBoundary:
    """The controlled mediation boundary between isolated agents and the outside.

    An isolated agent may *request* external information; it may not retrieve it.
    Only an explicitly authorized mediator (the workspace orchestrator) may resolve
    the request, and only a sanitized result is returned to the agent.
    """

    def __init__(self, *, authorized_mediators: Iterable[str]) -> None:
        mediators = tuple(str(item) for item in authorized_mediators)
        if not mediators:
            raise SandboxPolicyError("escalation boundary requires at least one authorized mediator")
        self._mediators = frozenset(mediators)
        self._open: dict[str, EscalationRequest] = {}
        self._resolved: dict[str, EscalationResult] = {}

    def raise_request(self, request: EscalationRequest, *, now: datetime | None = None) -> EscalationRequest:
        if request.escalation_id in self._open or request.escalation_id in self._resolved:
            raise SandboxPolicyError("escalation id already used")
        self._open[request.escalation_id] = request
        return request

    def resolve(self, escalation_id: str, *, mediator: str, sanitized_result: str, now: datetime | None = None) -> EscalationResult:
        if mediator not in self._mediators:
            raise SandboxPolicyError("only an authorized mediator may resolve an escalation")
        request = self._open.pop(escalation_id, None)
        if request is None:
            raise SandboxPolicyError("unknown or already-resolved escalation")
        moment = now or datetime.now(timezone.utc)
        result = EscalationResult(
            escalation_id=escalation_id,
            disposition="resolved",
            sanitized_result=sanitized_result,
            mediator=mediator,
            resolved_at_utc=moment.isoformat(),
        )
        self._resolved[escalation_id] = result
        return result

    @property
    def open_requests(self) -> tuple[EscalationRequest, ...]:
        return tuple(self._open.values())