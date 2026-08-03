from __future__ import annotations
from typing import Any
from ..common.mathx import clamp

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

def _normalized(profile: dict[str, Any], dimension: str) -> float:
    value = float(profile.get(dimension, 0.5))
    return clamp(value)

def route(request: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    requirements = request.get("requirements", {})
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(request.get("weights", {}))
    required_domains = set(map(str, request.get("domains", [])))
    max_risk = float(request.get("max_risk", 1.0))
    max_cost = float(request.get("max_cost", float("inf")))
    ranked = []
    for agent in agents:
        exclusions = []
        if float(agent.get("risk", 0.5)) > max_risk:
            exclusions.append("risk_budget")
        if float(agent.get("estimated_cost", 0.0)) > max_cost:
            exclusions.append("cost_budget")
        agent_domains = set(map(str, agent.get("domains", [])))
        domain_fit = 1.0 if not required_domains else len(agent_domains & required_domains) / len(required_domains)
        components = {}
        total = 0.0
        for dimension, weight in weights.items():
            if dimension == "domain_fit":
                value = domain_fit
            elif dimension in {"latency", "cost"}:
                value = 1.0 - _normalized(agent, dimension)
            else:
                value = _normalized(agent, dimension)
            minimum = requirements.get(dimension)
            if minimum is not None and value < float(minimum):
                exclusions.append(f"minimum_{dimension}")
            components[dimension] = round(value, 6)
            total += float(weight) * value
        calibration_penalty = float(agent.get("calibration_error", 0.0))
        failure_penalty = min(0.5, 0.05 * len(agent.get("known_failure_modes", [])))
        score = total - calibration_penalty - failure_penalty
        ranked.append({
            "agent_id": agent.get("id"),
            "eligible": not exclusions,
            "score": round(score, 6),
            "components": components,
            "exclusions": sorted(set(exclusions)),
            "known_failure_modes": agent.get("known_failure_modes", []),
        })
    ranked.sort(key=lambda x: (not x["eligible"], -x["score"], str(x["agent_id"])))
    selected = next((item for item in ranked if item["eligible"]), None)
    return {
        "request_id": request.get("id"),
        "selected_agent": selected["agent_id"] if selected else None,
        "ranked_candidates": ranked,
        "abstained": selected is None,
        "reason": None if selected else "no candidate satisfies hard constraints",
    }

def compose_team(request: dict[str, Any], agents: list[dict[str, Any]], max_agents: int = 3) -> dict[str, Any]:
    primary = route(request, agents)
    eligible_ids = [x["agent_id"] for x in primary["ranked_candidates"] if x["eligible"]]
    selected: list[str] = []
    covered_failures: set[str] = set()
    for agent_id in eligible_ids:
        agent = next(a for a in agents if a.get("id") == agent_id)
        failures = set(map(str, agent.get("known_failure_modes", [])))
        if not selected or not failures.issubset(covered_failures):
            selected.append(agent_id)
            covered_failures |= failures
        if len(selected) >= max_agents:
            break
    return {
        "request_id": request.get("id"),
        "team": selected,
        "primary": selected[0] if selected else None,
        "coordination_required": len(selected) > 1,
        "max_agents": max_agents,
        "note": "Profiles describe measured task behavior, not human personality or protected traits.",
    }
