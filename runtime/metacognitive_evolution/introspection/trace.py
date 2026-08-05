from __future__ import annotations
from collections import Counter
from typing import Any

ALLOWED_EVENT_TYPES = {
    "input_received",
    "skill_selected",
    "orchestration_selected",
    "tool_requested",
    "tool_result",
    "evidence_added",
    "assumption_added",
    "hypothesis_updated",
    "memory_read",
    "memory_written",
    "decision",
    "validation",
    "rollback",
    "output",
}


def validate_events(events: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, event in enumerate(events):
        event_id = str(event.get("event_id", ""))
        if not event_id:
            errors.append(f"event {index} lacks event_id")
        elif event_id in seen:
            errors.append(f"duplicate event_id: {event_id}")
        seen.add(event_id)
        if event.get("event_type") not in ALLOWED_EVENT_TYPES:
            errors.append(f"event {event_id or index} has unknown event_type")
        if "timestamp" not in event:
            errors.append(f"event {event_id or index} lacks timestamp")
        if "summary" not in event:
            errors.append(f"event {event_id or index} lacks summary")
        if "private_chain_of_thought" in event:
            errors.append(
                f"event {event_id or index} improperly contains private chain-of-thought"
            )
    return errors


def reconstruct(trace: dict[str, Any]) -> dict[str, Any]:
    events = list(trace.get("events", []))
    errors = validate_events(events)
    ordered = sorted(
        events, key=lambda x: (str(x.get("timestamp", "")), str(x.get("event_id", "")))
    )
    counts = Counter(str(e.get("event_type")) for e in ordered)
    skills = [
        e.get("capability_id")
        for e in ordered
        if e.get("event_type") == "skill_selected"
    ]
    orchestrations = [
        e.get("capability_id")
        for e in ordered
        if e.get("event_type") == "orchestration_selected"
    ]
    assumptions = [
        e.get("artifact_id")
        for e in ordered
        if e.get("event_type") == "assumption_added"
    ]
    evidence = [
        e.get("artifact_id") for e in ordered if e.get("event_type") == "evidence_added"
    ]
    memories = [
        e.get("artifact_id") for e in ordered if e.get("event_type") == "memory_read"
    ]
    decisions = [
        {
            "event_id": e.get("event_id"),
            "summary": e.get("summary"),
            "evidence_refs": e.get("evidence_refs", []),
            "assumption_refs": e.get("assumption_refs", []),
            "alternatives": e.get("alternatives", []),
        }
        for e in ordered
        if e.get("event_type") == "decision"
    ]
    orphan_decisions = [
        d["event_id"]
        for d in decisions
        if not d["evidence_refs"] and not d["assumption_refs"]
    ]
    validation_results = [e for e in ordered if e.get("event_type") == "validation"]
    return {
        "trace_id": trace.get("trace_id"),
        "valid": not errors,
        "errors": errors,
        "event_counts": dict(sorted(counts.items())),
        "selected_skills": [x for x in skills if x],
        "selected_orchestrations": [x for x in orchestrations if x],
        "assumption_influences": [x for x in assumptions if x],
        "evidence_influences": [x for x in evidence if x],
        "memory_influences": [x for x in memories if x],
        "decisions": decisions,
        "orphan_decisions": orphan_decisions,
        "validation_count": len(validation_results),
        "timeline": [
            {
                "timestamp": e.get("timestamp"),
                "event_type": e.get("event_type"),
                "summary": e.get("summary"),
                "capability_id": e.get("capability_id"),
            }
            for e in ordered
        ],
        "privacy_note": (
            "This report reconstructs declared operational events and evidence links. "
            "It does not capture or require private chain-of-thought."
        ),
    }


def compare_alternatives(trace: dict[str, Any]) -> dict[str, Any]:
    result = reconstruct(trace)
    alternatives = []
    for decision in result["decisions"]:
        for alternative in decision.get("alternatives", []):
            alternatives.append(
                {
                    "decision_event_id": decision["event_id"],
                    "alternative": alternative,
                }
            )
    return {
        "trace_id": result["trace_id"],
        "alternative_count": len(alternatives),
        "alternatives": alternatives,
        "unexplored_decision_count": sum(
            1 for d in result["decisions"] if not d.get("alternatives")
        ),
    }
