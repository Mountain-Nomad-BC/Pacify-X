"""Explainable task classification over compact text metadata only."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping


TOKEN = re.compile(r"[a-z0-9]+")
DEFAULT_TAXONOMY: Mapping[str, tuple[str, ...]] = {
    "build": ("build", "create", "implement", "scaffold", "generate"),
    "diagnosis": ("bug", "diagnose", "failure", "fix", "repair", "traceback"),
    "governance": ("approval", "authorization", "governance", "policy", "permission"),
    "onboarding": ("bootstrap", "existing", "intake", "new project", "onboard"),
    "orchestration": ("agent", "dag", "orchestrate", "schedule", "workflow"),
    "research": ("compare", "paper", "research", "source", "study"),
    "retrieval": (
        "citation",
        "graph",
        "knowledge",
        "retrieval",
        "retrieve",
        "search",
        "vector",
    ),
    "security": ("auth", "secret", "security", "threat", "vulnerability"),
    "validation": ("acceptance", "evidence", "test", "validate", "verify"),
}
DEFAULT_TASK_CLASSES: Mapping[str, tuple[str, ...]] = {
    "read_only": ("analyze", "inspect", "map", "read", "review"),
    "mutation": (
        "build",
        "change",
        "create",
        "delete",
        "edit",
        "fix",
        "implement",
        "install",
        "move",
        "write",
    ),
    "verification": ("acceptance", "evidence", "test", "validate", "verify"),
}


@dataclass(frozen=True, slots=True)
class ClassificationRecord:
    task_classes: tuple[str, ...]
    domains: tuple[str, ...]
    confidence: float
    matched_terms: tuple[str, ...]
    route: str
    explanation: str


def classify_task(
    text: str,
    *,
    confidence_threshold: float = 0.34,
    taxonomy: Mapping[str, tuple[str, ...]] = DEFAULT_TAXONOMY,
) -> ClassificationRecord:
    if not text.strip():
        raise ValueError("task text must not be empty")
    if not 0 < confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be in (0, 1]")
    lowered = " ".join(TOKEN.findall(text.casefold()))

    def matches(groups: Mapping[str, tuple[str, ...]]) -> dict[str, set[str]]:
        return {
            name: {term for term in terms if term in lowered}
            for name, terms in groups.items()
            if any(term in lowered for term in terms)
        }

    domain_matches = matches(taxonomy)
    class_matches = matches(DEFAULT_TASK_CLASSES)
    best = max((len(values) for values in domain_matches.values()), default=0)
    selected_domains = tuple(
        sorted(
            name
            for name, values in domain_matches.items()
            if len(values) >= max(1, best - 1)
        )
    )
    selected_classes = tuple(sorted(class_matches)) or ("read_only",)
    terms = (
        tuple(sorted(set().union(*domain_matches.values(), *class_matches.values())))
        if (domain_matches or class_matches)
        else ()
    )
    confidence = min(
        0.99, 0.18 + 0.16 * len(terms) + (0.08 if selected_domains else 0.0)
    )
    route = (
        "select"
        if selected_domains and confidence >= confidence_threshold
        else "broader_metadata_lookup"
    )
    return ClassificationRecord(
        selected_classes,
        selected_domains or ("general",),
        round(confidence, 3),
        terms,
        route,
        f"matched {len(terms)} taxonomy term(s); domains={','.join(selected_domains or ('general',))}",
    )
