"""Bounded agent-profile analysis; supplied traits do not grant execution authority."""

from __future__ import annotations
from typing import Any
from ...numeric_inputs import (
    analysis_payload,
    bounded_integer,
    bounded_mapping,
    bounded_sequence,
    bounded_text,
    finite_number,
)

DEFAULT_WEIGHTS = {
    "precision": 0.24,
    "evidence_strictness": 0.20,
    "domain_fit": 0.18,
    "depth": 0.12,
    "latency": 0.08,
    "cost": 0.08,
    "creativity": 0.05,
    "memory_efficiency": 0.05,
}


def _names(value, name):
    rows = [
        bounded_text(item, name) for item in bounded_sequence(value, name, maximum=64)
    ]
    if len(rows) != len(set(rows)):
        raise ValueError(f"{name} must have unique canonical identities")
    return rows


def route(request: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    analysis_payload({"request": request, "agents": agents})
    request = bounded_mapping(request, "routing request", maximum=16)
    if set(request) - {
        "id",
        "requirements",
        "weights",
        "domains",
        "max_risk",
        "max_cost",
    }:
        raise ValueError("unknown routing request field")
    request_id = (
        bounded_text(request["id"], "request identity") if "id" in request else None
    )
    requirements = bounded_mapping(
        request.get("requirements", {}), "requirements", maximum=8
    )
    supplied_weights = bounded_mapping(request.get("weights", {}), "weights", maximum=8)
    if (set(requirements) | set(supplied_weights)) - set(DEFAULT_WEIGHTS):
        raise ValueError("unknown routing dimension")
    requirements = {
        key: finite_number(value, "required desirability", minimum=0, maximum=1)
        for key, value in requirements.items()
    }
    weights = {**DEFAULT_WEIGHTS, **supplied_weights}
    weights = {
        key: finite_number(value, "dimension weight", minimum=0)
        for key, value in weights.items()
    }
    if not any(weights.values()):
        raise ValueError("at least one dimension weight must be positive")
    required_domains = set(_names(request.get("domains", []), "required domains"))
    max_risk = finite_number(
        request.get("max_risk", 1.0), "maximum risk", minimum=0, maximum=1
    )
    max_cost = (
        finite_number(request["max_cost"], "maximum estimated cost", minimum=0)
        if "max_cost" in request
        else None
    )
    parsed = []
    seen = set()
    for agent in bounded_sequence(agents, "agents", maximum=256):
        agent = bounded_mapping(agent, "agent profile", maximum=64)
        identity = bounded_text(agent.get("id"), "agent identity")
        if identity in seen:
            raise ValueError("agent identities must be unique")
        seen.add(identity)
        domains = set(_names(agent.get("domains", []), "agent domains"))
        traits = {
            key: finite_number(agent[key], "agent trait", minimum=0, maximum=1)
            for key in DEFAULT_WEIGHTS
            if key != "domain_fit" and key in agent
        }
        parsed.append(
            {
                "id": identity,
                "domains": domains,
                "traits": traits,
                "has_risk": "risk" in agent,
                "has_estimated_cost": "estimated_cost" in agent,
                "risk": finite_number(
                    agent.get("risk", 0.5), "agent risk", minimum=0, maximum=1
                ),
                "estimated_cost": finite_number(
                    agent.get("estimated_cost", 0.0), "estimated cost", minimum=0
                ),
                "calibration_error": finite_number(
                    agent.get("calibration_error", 0.0),
                    "calibration error",
                    minimum=0,
                    maximum=1,
                ),
                "known_failure_modes": _names(
                    agent.get("known_failure_modes", []), "known failure modes"
                ),
            }
        )
    ranked = []
    for agent in parsed:
        exclusions = []
        if "max_risk" in request and not agent["has_risk"]:
            exclusions.append("missing_risk")
        if max_cost is not None and not agent["has_estimated_cost"]:
            exclusions.append("missing_estimated_cost")
        if agent["risk"] > max_risk:
            exclusions.append("risk_budget")
        if max_cost is not None and agent["estimated_cost"] > max_cost:
            exclusions.append("cost_budget")
        if not required_domains <= agent["domains"]:
            exclusions.append("required_domains")
        domain_fit = (
            len(agent["domains"] & required_domains) / len(required_domains)
            if required_domains
            else 1.0
        )
        components = {}
        total = 0.0
        for dimension, weight in weights.items():
            if dimension == "domain_fit":
                value = domain_fit
            else:
                value = agent["traits"].get(dimension, 0.5)
                if dimension in {"latency", "cost"}:
                    value = 1.0 - value
            if dimension in requirements:
                if dimension != "domain_fit" and dimension not in agent["traits"]:
                    exclusions.append(f"missing_{dimension}")
                elif value < requirements[dimension]:
                    exclusions.append(f"minimum_{dimension}")
            components[dimension] = round(value, 6)
            total += weight * value
        score = finite_number(
            total
            - agent["calibration_error"]
            - min(0.5, 0.05 * len(agent["known_failure_modes"])),
            "routing score",
        )
        ranked.append(
            {
                "agent_id": agent["id"],
                "eligible": not exclusions,
                "score": round(score, 6),
                "components": components,
                "exclusions": sorted(set(exclusions)),
                "known_failure_modes": agent["known_failure_modes"],
            }
        )
    ranked.sort(key=lambda row: (not row["eligible"], -row["score"], row["agent_id"]))
    selected = next((row for row in ranked if row["eligible"]), None)
    return {
        "request_id": request_id,
        "selected_agent": selected["agent_id"] if selected else None,
        "ranked_candidates": ranked,
        "abstained": selected is None,
        "reason": None if selected else "no candidate satisfies hard constraints",
        "authority": "supplied-profile analysis; current execution admission is required separately",
        "cost_semantics": "estimated_cost is the hard budget; cost and latency are normalized burdens whose complements are scored",
    }


def compose_team(
    request: dict[str, Any], agents: list[dict[str, Any]], max_agents: int = 3
) -> dict[str, Any]:
    max_agents = bounded_integer(max_agents, "max_agents", maximum=256)
    primary = route(request, agents)
    selected = []
    covered_failures = set()
    for agent in primary["ranked_candidates"]:
        if not agent["eligible"]:
            continue
        failures = set(agent["known_failure_modes"])
        if not selected or not failures.issubset(covered_failures):
            selected.append(agent["agent_id"])
            covered_failures |= failures
        if len(selected) >= max_agents:
            break
    return {
        "request_id": primary["request_id"],
        "team": selected,
        "primary": selected[0] if selected else None,
        "coordination_required": len(selected) > 1,
        "max_agents": max_agents,
        "note": "Profiles describe measured task behavior, not human personality or protected traits.",
        "limits": "Failure-label diversity is a heuristic, not complementary competence. This proposal does not reserve aggregate resources or grant execution authority.",
    }
