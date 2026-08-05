"""Governed, metadata-first access to the local Agency specialist provider.

Agent bodies are inert reference content.  This module validates their hashes,
routes from metadata, and hydrates only an explicitly selected bounded panel.
Nothing in a prompt, manifest, or frontmatter grants tools or execution rights.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from .capability_routing import TaskEnvelope, normalize_task
from .json_io import load_json_object


REGISTRY_PATH = Path("registry/agency_agent_registry.json")
POLICY_PATH = Path("policies/agency-agent-runtime.json")
MANIFEST_SCHEMA = Path("contracts/agents/agency-agent-manifest.schema.json")
RESULT_SCHEMA = "contracts/agents/agent-result.schema.json"
TASK_SCHEMA = Path("contracts/agents/agent-task-envelope.schema.json")
ROUTE_SCHEMA = Path("contracts/agents/agent-route-plan.schema.json")
TOKEN = re.compile(r"[a-z0-9][a-z0-9_+.#/-]*", re.IGNORECASE)
HIGH_RISK_TERMS = {
    "billing",
    "clinical",
    "compliance",
    "credential",
    "delete",
    "deploy",
    "employment",
    "healthcare",
    "incident",
    "investment",
    "legal",
    "loan",
    "medical",
    "patient",
    "payment",
    "penetration",
    "privacy",
    "production",
    "secret",
    "security",
    "tax",
}
ROLE_TERMS = {
    "reviewer": {"audit", "check", "review", "validate", "verify"},
    "operator": {
        "build",
        "configure",
        "create",
        "develop",
        "fix",
        "implement",
        "migrate",
    },
    "advisor": {"analyze", "design", "plan", "research", "strategy", "synthesize"},
}
CAPABILITY_ALIASES = {
    "api": {"backend", "integration", "architecture"},
    "auth": {"identity_access", "security"},
    "database": {"backend", "data_engineering", "database"},
    "deploy": {"devops", "sre_reliability", "testing"},
    "llm": {"ai_ml", "llm_training", "multi_agent"},
    "rag": {"ai_ml", "search_retrieval"},
    "ui": {"accessibility", "design", "frontend"},
    "ux": {"accessibility", "design", "research"},
}
ALLOWED_LIFECYCLES = {"active", "advisory"}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _tokens(*values: object) -> set[str]:
    result: set[str] = set()
    for value in values:
        if isinstance(value, (list, tuple, set)):
            result.update(_tokens(*value))
        elif value is not None:
            result.update(
                item.casefold().strip("./-") for item in TOKEN.findall(str(value))
            )
    return {item for item in result if item}


def _provider_path(root: Path, relative: str) -> Path:
    root = root.resolve(strict=True)
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"provider path must be project-relative: {relative}")
    candidate = (root / value).resolve(strict=True)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError(
            f"provider path escapes the framework or is not a file: {relative}"
        )
    return candidate


def load_registry(root: Path) -> dict[str, Any]:
    registry = load_json_object(_provider_path(root, REGISTRY_PATH.as_posix()))
    if registry.get("provider_id") != "agency-agents":
        raise ValueError("agency provider registry has the wrong provider_id")
    if registry.get("agent_count") != len(registry.get("agents", [])):
        raise ValueError("agency provider agent_count does not match its records")
    return registry


def validate_provider(root: Path) -> dict[str, Any]:
    """Validate identity, containment, hashes, manifests, and graph references."""
    registry = load_registry(root)
    errors: list[str] = []
    ids = [str(item.get("agent_id", "")) for item in registry["agents"]]
    known_ids = set(ids)
    if len(known_ids) != len(ids):
        errors.append("agent IDs are not unique")
    if registry["activation_policy"].get("max_reviewers") != 3:
        errors.append("provider must enforce a maximum of three reviewers")
    if registry["activation_policy"].get("prompt_grants_authority") is not False:
        errors.append("prompt content must never grant runtime authority")

    status_counts: dict[str, int] = {}
    lifecycle_counts: dict[str, int] = {}
    checked_bytes = 0
    for item in registry["agents"]:
        agent_id = str(item.get("agent_id", ""))
        try:
            body_path = _provider_path(root, item["path"])
            manifest_path = _provider_path(root, item["manifest_path"])
            body = body_path.read_bytes()
            manifest_bytes = manifest_path.read_bytes()
            checked_bytes += len(body) + len(manifest_bytes)
            if _sha256_bytes(body) != item.get("body_sha256"):
                errors.append(f"{agent_id}: body hash mismatch")
            if _sha256_bytes(manifest_bytes) != item.get("manifest_sha256"):
                errors.append(f"{agent_id}: manifest hash mismatch")
            manifest = json.loads(manifest_bytes)
            if manifest.get("agent_id") != agent_id:
                errors.append(f"{agent_id}: manifest identity mismatch")
            if manifest.get("canonical", {}).get("sha256") != item.get("body_sha256"):
                errors.append(f"{agent_id}: canonical body provenance mismatch")
            if manifest.get("tool_requests_are_grants") is not False:
                errors.append(
                    f"{agent_id}: tool requests are not explicitly non-authoritative"
                )
            if (
                manifest.get("memory_namespace")
                != "project:{project_id}:agent:{agent_id}"
            ):
                errors.append(f"{agent_id}: memory namespace is not project-scoped")
            if manifest.get("output_contract") != RESULT_SCHEMA:
                errors.append(f"{agent_id}: result contract mismatch")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append(f"{agent_id}: {type(exc).__name__}: {exc}")
        status = str(item.get("source_audit_status", "missing"))
        lifecycle = str(item.get("lifecycle_state", "missing"))
        status_counts[status] = status_counts.get(status, 0) + 1
        lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
        for target in item.get("handoffs", []):
            if target not in known_ids:
                errors.append(f"{agent_id}: unknown handoff {target}")

    graph_path = root / "registry" / "agency_agent_graph.json"
    if not graph_path.is_file():
        errors.append("agency provider graph is missing")
    else:
        try:
            if load_json_object(graph_path) != build_agent_graph(root):
                errors.append("agency provider graph is stale or non-deterministic")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append(
                f"agency provider graph unavailable: {type(exc).__name__}: {exc}"
            )

    return {
        "valid": not errors,
        "provider_id": registry["provider_id"],
        "agent_count": len(ids),
        "body_count": len(ids),
        "manifest_count": len(ids),
        "source_audit_status_counts": dict(sorted(status_counts.items())),
        "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
        "checked_bytes": checked_bytes,
        "eager_body_hydration": 0,
        "errors": errors,
    }


def build_agent_graph(root: Path) -> dict[str, Any]:
    """Build the exact provider graph from the canonical local registry."""
    registry = load_registry(root)
    agents = registry["agents"]
    by_id = {item["agent_id"]: item for item in agents}
    divisions = sorted({str(item["division"]) for item in agents})
    capabilities = sorted(
        {str(value) for item in agents for value in item.get("capabilities", [])}
    )
    nodes = [
        {"id": f"division.{value}", "type": "division", "label": value}
        for value in divisions
    ]
    nodes.extend(
        {"id": f"capability.{value}", "type": "capability", "label": value}
        for value in capabilities
    )
    nodes.extend(
        {
            "id": item["agent_id"],
            "type": "agent",
            "label": item["name"],
            "division": item["division"],
            "risk_tier": item["risk_tier"],
            "source_audit_status": item["source_audit_status"],
            "lifecycle_state": item["lifecycle_state"],
        }
        for item in agents
    )
    edges: list[dict[str, str]] = []
    for item in agents:
        source = item["agent_id"]
        edges.append(
            {
                "source": source,
                "target": f"division.{item['division']}",
                "type": "belongs_to",
            }
        )
        edges.extend(
            {"source": source, "target": f"capability.{value}", "type": "provides"}
            for value in item.get("capabilities", [])
        )
        for target in item.get("handoffs", []):
            edges.append({"source": source, "target": target, "type": "hands_off_to"})
            if by_id[target].get("role_mode") == "reviewer":
                edges.append(
                    {"source": source, "target": target, "type": "reviewed_by"}
                )
    nodes.sort(key=lambda item: (item["type"], item["id"]))
    edges.sort(key=lambda item: (item["source"], item["type"], item["target"]))
    payload: dict[str, Any] = {
        "schema_version": "2.0.0",
        "provider_id": registry["provider_id"],
        "nodes": nodes,
        "edges": edges,
        "metrics": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "agent_nodes": len(agents),
            "capability_nodes": len(capabilities),
            "division_nodes": len(divisions),
        },
    }
    payload["revision"] = _stable(payload)
    return payload


@dataclass(frozen=True, slots=True)
class AgentCandidate:
    agent_id: str
    score: float
    matched_channels: tuple[str, ...]
    matched_terms: tuple[str, ...]
    lifecycle_state: str
    role_mode: str
    risk_tier: str


def _candidate_payload(candidate: AgentCandidate) -> dict[str, Any]:
    payload = asdict(candidate)
    payload["matched_channels"] = list(candidate.matched_channels)
    payload["matched_terms"] = list(candidate.matched_terms)
    return payload


def _requested_capabilities(terms: set[str], envelope: TaskEnvelope) -> set[str]:
    result = set(envelope.capabilities) | set(envelope.domain)
    for term in terms:
        result.update(CAPABILITY_ALIASES.get(term, set()))
    return result


def _role_intent(terms: set[str]) -> str | None:
    scores = {role: len(terms & hints) for role, hints in ROLE_TERMS.items()}
    role, score = max(scores.items(), key=lambda item: (item[1], item[0]))
    return role if score else None


def discover_agents(
    root: Path,
    request: str,
    *,
    constraints: Iterable[str] = (),
    include_reference_only: bool = False,
) -> tuple[TaskEnvelope, list[AgentCandidate]]:
    """Retrieve from metadata only; no agent body or manifest is opened."""
    registry = load_registry(root)
    envelope = normalize_task(request, constraints=constraints)
    query_terms = _tokens(request, *constraints)
    requested = _requested_capabilities(query_terms, envelope)
    role_intent = _role_intent(query_terms)
    candidates: list[AgentCandidate] = []
    for item in registry["agents"]:
        lifecycle = str(item["lifecycle_state"])
        if lifecycle not in ALLOWED_LIFECYCLES and not include_reference_only:
            continue
        negative = query_terms & _tokens(item.get("negative_matches", []))
        if negative:
            continue
        name_alias = _tokens(item.get("name"), item.get("aliases", []))
        description = _tokens(item.get("description"))
        capabilities = _tokens(item.get("capabilities", []))
        division = _tokens(item.get("division"))
        channel_terms = {
            "identity": query_terms & name_alias,
            "description": query_terms & description,
            "capability": requested & capabilities,
            "division": (query_terms | set(envelope.domain)) & division,
        }
        channels = tuple(sorted(key for key, value in channel_terms.items() if value))
        normalized_name = " ".join(_tokens(item.get("name")))
        normalized_query = " ".join(sorted(query_terms))
        exact_identity = bool(normalized_name and normalized_name in normalized_query)
        # A lone generic keyword is insufficient. Require independent metadata
        # agreement, or an exact specialist identity plus one contextual signal.
        if len(channels) < 2 and not (exact_identity and channels):
            continue
        score = 0.0
        score += min(35.0, 18.0 * len(channel_terms["identity"]))
        score += min(20.0, 4.0 * len(channel_terms["description"]))
        score += min(30.0, 12.0 * len(channel_terms["capability"]))
        score += min(8.0, 8.0 * len(channel_terms["division"]))
        if role_intent and item.get("role_mode") == role_intent:
            score += 7.0
        if lifecycle == "advisory":
            score -= 4.0
        if lifecycle == "reference_only":
            score -= 25.0
        matched = tuple(sorted(set().union(*channel_terms.values())))
        candidates.append(
            AgentCandidate(
                agent_id=item["agent_id"],
                score=round(max(0.0, min(100.0, score)), 3),
                matched_channels=channels,
                matched_terms=matched,
                lifecycle_state=lifecycle,
                role_mode=item["role_mode"],
                risk_tier=item["risk_tier"],
            )
        )
    candidates.sort(
        key=lambda item: (-item.score, item.risk_tier == "high", item.agent_id)
    )
    return envelope, candidates


def _choose_reviewers(
    primary: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    *,
    high_risk: bool,
    maximum: int,
) -> list[str]:
    rows: list[tuple[float, str]] = []
    primary_caps = set(primary.get("capabilities", []))
    explicit = set(primary.get("handoffs", []))
    for agent_id, candidate in by_id.items():
        if (
            agent_id == primary["agent_id"]
            or candidate.get("lifecycle_state") not in ALLOWED_LIFECYCLES
        ):
            continue
        caps = set(candidate.get("capabilities", []))
        governance = bool(
            caps & {"compliance_governance", "privacy", "security", "testing"}
        )
        if (
            agent_id not in explicit
            and candidate.get("role_mode") != "reviewer"
            and not (high_risk and governance)
        ):
            continue
        score = 40.0 if agent_id in explicit else 0.0
        score += 20.0 if candidate.get("role_mode") == "reviewer" else 0.0
        score += min(20.0, 5.0 * len(primary_caps & caps))
        score += 20.0 if high_risk and governance else 0.0
        rows.append((score, agent_id))
    rows.sort(key=lambda row: (-row[0], row[1]))
    reviewers: list[str] = []
    review_functions: set[tuple[str, str]] = set()
    for _, agent_id in rows:
        candidate = by_id[agent_id]
        function = (str(candidate.get("division")), str(candidate.get("role_mode")))
        if function in review_functions:
            continue
        reviewers.append(agent_id)
        review_functions.add(function)
        if len(reviewers) >= maximum:
            break
    return reviewers


def route_agents(
    root: Path,
    request: str,
    *,
    constraints: Iterable[str] = (),
    limit: int = 8,
    max_reviewers: int = 3,
) -> dict[str, Any]:
    if not 0 <= max_reviewers <= 3:
        raise ValueError("max_reviewers must be between zero and three")
    registry = load_registry(root)
    envelope, candidates = discover_agents(root, request, constraints=constraints)
    task_id = "agent-task-" + envelope.task_envelope_sha256[:16]
    if not candidates or candidates[0].score < 18.0:
        return {
            "valid": False,
            "task_id": task_id,
            "task_envelope_sha256": envelope.task_envelope_sha256,
            "primary_agent": None,
            "reviewers": [],
            "score_evidence": [_candidate_payload(item) for item in candidates[:limit]],
            "risk_tier": "medium",
            "requires_human_review": False,
            "unresolved_requirements": [
                "No specialist passed the bounded multi-signal routing floor; clarify the domain and deliverable."
            ],
            "authority_granted": False,
            "hydrated_agent_count": 0,
        }
    by_id = {item["agent_id"]: item for item in registry["agents"]}
    primary = by_id[candidates[0].agent_id]
    terms = _tokens(request, *constraints)
    high_risk = bool(terms & HIGH_RISK_TERMS) or primary.get("risk_tier") == "high"
    reviewers = _choose_reviewers(
        primary, by_id, high_risk=high_risk, maximum=max_reviewers
    )
    unresolved: list[str] = []
    if candidates[0].score < 30.0:
        unresolved.append(
            "Route confidence is low; confirm the specialist and deliverable before activation."
        )
    if high_risk and not reviewers:
        unresolved.append("High-risk work requires an independent specialist reviewer.")
    route = {
        "valid": not unresolved,
        "task_id": task_id,
        "task_envelope_sha256": envelope.task_envelope_sha256,
        "primary_agent": primary["agent_id"],
        "reviewers": reviewers,
        "score_evidence": [_candidate_payload(item) for item in candidates[:limit]],
        "risk_tier": "high" if high_risk else primary["risk_tier"],
        "requires_human_review": high_risk
        or bool(primary.get("requires_human_review")),
        "unresolved_requirements": unresolved,
        "authority_granted": False,
        "hydrated_agent_count": 0,
    }
    route["route_receipt_sha256"] = _stable(route)
    return route


def _domain_content(body: str) -> str:
    marker = "PACIFY-X Operational Contract"
    position = body.find(marker)
    if position < 0:
        return body.rstrip()
    heading = body.rfind("\n##", 0, position)
    return body[: heading if heading >= 0 else position].rstrip()


def hydrate_agents(
    root: Path,
    agent_ids: Sequence[str],
    *,
    project_id: str,
    max_agents: int = 4,
    max_total_bytes: int = 512_000,
) -> dict[str, Any]:
    if not project_id.strip() or any(
        value in project_id for value in ("/", "\\", "..")
    ):
        raise ValueError("project_id must be a non-empty namespace token")
    unique_ids = tuple(dict.fromkeys(agent_ids))
    if not unique_ids or len(unique_ids) > max_agents or max_agents > 4:
        raise ValueError("hydration requires one to four unique selected agents")
    registry = load_registry(root)
    by_id = {item["agent_id"]: item for item in registry["agents"]}
    hydrated: list[dict[str, Any]] = []
    total_bytes = 0
    for agent_id in unique_ids:
        item = by_id.get(agent_id)
        if item is None:
            raise ValueError(f"unknown agent_id: {agent_id}")
        if item.get("lifecycle_state") not in ALLOWED_LIFECYCLES:
            raise ValueError(
                f"agent is reference-only and cannot be hydrated: {agent_id}"
            )
        body_path = _provider_path(root, item["path"])
        manifest_path = _provider_path(root, item["manifest_path"])
        body_bytes = body_path.read_bytes()
        manifest_bytes = manifest_path.read_bytes()
        if _sha256_bytes(body_bytes) != item["body_sha256"]:
            raise ValueError(f"body hash mismatch: {agent_id}")
        if _sha256_bytes(manifest_bytes) != item["manifest_sha256"]:
            raise ValueError(f"manifest hash mismatch: {agent_id}")
        domain = _domain_content(body_bytes.decode("utf-8"))
        manifest = json.loads(manifest_bytes)
        material_bytes = len(domain.encode("utf-8")) + len(manifest_bytes)
        if total_bytes + material_bytes > max_total_bytes:
            raise ValueError("agent hydration byte budget exceeded")
        total_bytes += material_bytes
        hydrated.append(
            {
                "agent_id": agent_id,
                "manifest": manifest,
                "domain_content": domain,
                "memory_namespace": f"project:{project_id}:agent:{agent_id}",
                "authority_granted": False,
                "hydrated_bytes": material_bytes,
            }
        )
    receipt = {
        "project_id": project_id,
        "agent_ids": list(unique_ids),
        "hydrated_agent_count": len(hydrated),
        "hydrated_bytes": total_bytes,
        "max_agents": max_agents,
        "max_total_bytes": max_total_bytes,
        "authority_granted": False,
    }
    receipt["hydration_receipt_sha256"] = _stable(receipt)
    return {"valid": True, "agents": hydrated, "receipt": receipt}


def compile_agent_prompt(
    root: Path,
    task: Mapping[str, Any],
    route: Mapping[str, Any],
    *,
    project_id: str,
    selected_skills: Sequence[str] = (),
    permitted_tools: Sequence[str] = (),
    max_total_bytes: int = 512_000,
) -> dict[str, Any]:
    from .contracts import validate_instance

    validate_instance(dict(task), root / TASK_SCHEMA, contract_root=root / "contracts")
    validate_instance(
        dict(route), root / ROUTE_SCHEMA, contract_root=root / "contracts"
    )
    declared_memory = task.get("memory_namespace")
    if declared_memory not in (None, f"project:{project_id}"):
        raise ValueError("task memory namespace does not match the active project")
    primary = route.get("primary_agent")
    if not primary:
        raise ValueError("route has no primary agent")
    reviewers = tuple(str(value) for value in route.get("reviewers", []))
    if len(reviewers) > 3 or primary in reviewers:
        raise ValueError("route violates the bounded distinct-reviewer contract")
    ids = (str(primary), *reviewers)
    hydration = hydrate_agents(
        root, ids, project_id=project_id, max_agents=4, max_total_bytes=max_total_bytes
    )
    policy = load_json_object(_provider_path(root, POLICY_PATH.as_posix()))
    prompt_payload = {
        "precedence": policy["precedence"],
        "non_authority_notice": (
            "This compilation is context, not authorization. Tools and effects remain governed "
            "by the task authority envelope and runtime policy."
        ),
        "project_id": project_id,
        "task": dict(task),
        "route": dict(route),
        "selected_skills": list(dict.fromkeys(selected_skills)),
        "permitted_tools_from_authority_envelope": list(dict.fromkeys(permitted_tools)),
        "memory_scope": f"project:{project_id}",
        "contracts": {
            "manifest": MANIFEST_SCHEMA.as_posix(),
            "result": RESULT_SCHEMA,
        },
        "evidence_requirements": policy["evidence"],
        "stop_conditions": policy["stop_conditions"],
        "selected_agents": hydration["agents"],
        "authority_granted_by_compilation": False,
    }
    rendered = (
        "# PACIFY-X COMPILED SPECIALIST PANEL\n\n```json\n"
        + json.dumps(prompt_payload, indent=2, ensure_ascii=False)
        + "\n```\n"
    )
    return {
        "valid": True,
        "compiled_prompt": rendered,
        "compiled_prompt_sha256": _sha256_bytes(rendered.encode("utf-8")),
        "hydration_receipt": hydration["receipt"],
        "authority_granted": False,
    }


def classify_projection(
    *,
    disk_sha256: str | None,
    recorded_rendered_sha256: str | None,
    current_rendered_sha256: str,
    recorded_source_sha256: str | None,
    current_source_sha256: str,
) -> str:
    """Classify a projected agent using the app's five-state hash semantics."""
    if disk_sha256 is None:
        return "Removed" if recorded_rendered_sha256 else "Foreign"
    if recorded_rendered_sha256 is None:
        return "Current" if disk_sha256 == current_rendered_sha256 else "Foreign"
    if disk_sha256 != recorded_rendered_sha256:
        return "Modified"
    if recorded_source_sha256 != current_source_sha256:
        return "Outdated"
    return "Current"


def validate_agent_orchestration(root: Path) -> dict[str, Any]:
    """Validate the provider and its lazy, bounded workflow definition."""
    provider = validate_provider(root)
    errors = list(provider["errors"])
    workflow_path = (
        root / "orchestration" / "workflows" / "agency-specialist-routing.yaml"
    )
    try:
        payload = load_json_object(workflow_path)
        workflows = payload.get("workflows", [])
        if len(workflows) != 1 or workflows[0].get("id") != "agency-specialist-routing":
            errors.append("agency specialist orchestration identity mismatch")
        else:
            workflow = workflows[0]
            steps = workflow.get("steps", [])
            step_ids = {str(item.get("id")) for item in steps}
            if len(step_ids) != len(steps):
                errors.append("agency specialist orchestration step IDs are not unique")
            for step in steps:
                unknown = set(map(str, step.get("depends_on", []))) - step_ids
                if unknown:
                    errors.append(
                        f"{step.get('id')}: unknown dependencies {sorted(unknown)}"
                    )
            bounds = workflow.get("bounds", {})
            if bounds != {
                "primary_agents": 1,
                "max_reviewers": 3,
                "max_hydrated_agents": 4,
            }:
                errors.append("agency specialist orchestration bounds changed")
            required_steps = {
                "validate-provider",
                "route-metadata",
                "review-risk",
                "compile-selected",
                "authorize-effects",
                "verify-result",
                "release-context",
            }
            if step_ids != required_steps:
                errors.append("agency specialist orchestration lifecycle is incomplete")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        errors.append(f"workflow unavailable: {type(exc).__name__}: {exc}")
    return {
        "valid": not errors,
        "provider": provider,
        "workflow": "agency-specialist-routing",
        "errors": errors,
    }
