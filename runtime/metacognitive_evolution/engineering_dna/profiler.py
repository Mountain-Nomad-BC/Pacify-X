from __future__ import annotations
from collections import Counter, defaultdict
from typing import Any

PROHIBITED_FIELDS = {
    "personality", "intelligence", "iq", "race", "ethnicity", "religion", "sex",
    "gender", "sexual_orientation", "health", "disability", "age", "politics"
}

ALLOWED_PATTERN_TYPES = {
    "architecture_choice", "testing_practice", "release_practice", "documentation_practice",
    "failure_pattern", "repair_pattern", "dependency_pattern", "security_practice",
    "performance_practice", "review_practice"
}

def profile(events: list[dict[str, Any]], min_observations: int = 3) -> dict[str, Any]:
    violations = []
    counts = Counter()
    outcomes = defaultdict(lambda: {"success": 0, "failure": 0})
    examples = defaultdict(list)
    for event in events:
        forbidden = sorted(PROHIBITED_FIELDS & set(event))
        if forbidden:
            violations.append({"event_id": event.get("id"), "prohibited_fields": forbidden})
        pattern_type = str(event.get("pattern_type", ""))
        if pattern_type not in ALLOWED_PATTERN_TYPES:
            continue
        pattern = str(event.get("pattern", "")).strip()
        if not pattern:
            continue
        key = f"{pattern_type}:{pattern}"
        counts[key] += 1
        outcome = "success" if bool(event.get("successful", False)) else "failure"
        outcomes[key][outcome] += 1
        if len(examples[key]) < 3:
            examples[key].append(event.get("evidence_ref"))
    patterns = []
    for key, count in counts.items():
        if count < min_observations:
            continue
        success = outcomes[key]["success"]
        failure = outcomes[key]["failure"]
        pattern_type, pattern = key.split(":", 1)
        patterns.append({
            "pattern_type": pattern_type,
            "pattern": pattern,
            "observation_count": count,
            "success_rate": success / max(1, success + failure),
            "evidence_refs": [x for x in examples[key] if x],
            "confidence": min(1.0, count / (min_observations * 3)),
            "transfer_status": "candidate_only",
        })
    patterns.sort(key=lambda x: (-x["observation_count"], x["pattern_type"], x["pattern"]))
    return {
        "valid": not violations,
        "policy_violations": violations,
        "patterns": patterns,
        "limits": [
            "No personality, protected-trait, medical, or IQ inference.",
            "Patterns describe repository and workflow evidence only.",
            "Transfer requires target-context validation and human approval.",
        ],
    }

def compare_profiles(source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    s = {(p["pattern_type"], p["pattern"]): p for p in source.get("patterns", [])}
    t = {(p["pattern_type"], p["pattern"]): p for p in target.get("patterns", [])}
    shared = sorted(set(s) & set(t))
    source_only = sorted(set(s) - set(t))
    return {
        "shared_patterns": [{"pattern_type": a, "pattern": b} for a, b in shared],
        "source_only_candidates": [
            {
                "pattern_type": a,
                "pattern": b,
                "source_success_rate": s[(a, b)]["success_rate"],
                "transfer_requires_validation": True,
            }
            for a, b in source_only
        ],
    }
