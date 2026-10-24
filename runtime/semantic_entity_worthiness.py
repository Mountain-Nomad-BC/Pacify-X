"""Entity-worthiness test and the exclusion ledger for SEM-003 census.

Not every file is a semantic entity. A README does not deserve a compact
semantic address merely because it exists in the repository.

Worthiness test
---------------
A document is admitted only when it REPRESENTS or DEFINES a canonical,
retrievable PX concept. Concretely, it must match at least one governed
predicate: an authoritative specification, a contract, a policy, a procedure or
instruction, a skill, an architecture definition, operational knowledge, or a
canonical reference.

Explanatory mirrors, generated output, installation notes, examples and
duplicated provider prose are NOT admitted. They are recorded in an exclusion
ledger WITH a reason, so the decision is auditable rather than a silent filter.

This is deliberately conservative in one direction only: when a file is
ambiguous it is EXCLUDED and logged, because admitting non-entities pollutes
the taxonomy and consumes vocabulary that real entities need. Nothing is
admitted merely because it looks structured.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

EXCLUSION_SCHEMA = "px.semantic-exclusion-ledger/1.0"

# Governed predicates: a document qualifies if its path, name or front matter
# matches one of these. Each predicate names the canonical concept it defends.
WORTHY_PREDICATES: dict[str, tuple[str, ...]] = {
    "contract": ("contracts/", "contract", "schema", ".schema.json"),
    "policy": ("policies/", "policy", "governance/"),
    "skill": (".px/skills/", "/skills/", "skill"),
    "procedure": ("procedure", "playbook", "runbook", "checklist", "instructions"),
    "specification": ("spec", "standard", "convention", "protocol"),
    "architecture": ("architecture", "design", "adr", "blueprint"),
    "operational_knowledge": ("operations", "runbook", "operating", "maintenance"),
    "canonical_reference": ("reference", "catalog", "inventory", "registry"),
}

# Explicit non-entities. These never consume semantic-address space.
EXCLUSION_PATTERNS: dict[str, str] = {
    r"(?i)readme(\.md|\.rst|\.txt)?$": "readme-descriptive",
    r"(?i)(^|/)changelog(\.md)?$": "changelog-historical",
    r"(?i)(^|/)(contributing|code_of_conduct|security)(\.md)?$": "project-policy-document-not-px-entity",
    r"(?i)(^|/)license(\.md|$)": "legal-not-px-entity",
    r"(?i)(^|/)notice(\.md|$)": "legal-not-px-entity",
    r"(?i)(^|/)install(ation)?(\.md)?$": "installation-note-not-governed-entity",
    r"(?i)(^|/)getting_started(\.md)?$": "tutorial-not-governed-entity",
    r"(?i)(^|/)quickstart(\.md)?$": "tutorial-not-governed-entity",
    r"(?i)(^|/)example[s]?/": "example-not-canonical-entity",
    r"(?i)(^|/)sample[s]?/": "example-not-canonical-entity",
    r"(?i)(^|/)demo/": "example-not-canonical-entity",
    r"(?i)(^|/)tutorial[s]?/": "tutorial-not-governed-entity",
    r"(?i)(^|/)docs?/architecture/(data|vault)/": "generated-atlas-output",
    r"(?i)(^|/)atlas_offline": "generated-atlas-output",
    r"(?i)(^|/)graph_data\.js$": "generated-atlas-output",
    r"(?i)(^|/)\.px/skills/.*/(notes|scratch|tmp)/": "working-notes-not-entity",
    r"(?i)\.bak$|\.orig$|\.rej$|\.tmp$": "editor-scratch",
    r"(?i)(^|/)test[-_]?data/": "test-fixture-data",
    r"(?i)(^|/)fixtures?/": "test-fixture-data",
}

# Front-matter signals that a markdown file is a governed artifact.
_GOVERNED_FRONTMATTER = re.compile(
    r"(?i)^\s*(kind|type|category|governed|entity_kind|artifact_type)\s*[:=]"
)
_SKILL_FRONTMATTER = re.compile(r"(?i)^---\s*$")

_EXCLUSION_RE = [
    (re.compile(pattern), reason) for pattern, reason in EXCLUSION_PATTERNS.items()
]


@dataclass(frozen=True)
class ExclusionDecision:
    path: str
    admitted: bool
    reason: str
    matched_predicate: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "path": self.path,
            "admitted": self.admitted,
            "reason": self.reason,
            "matched_predicate": self.matched_predicate,
        }


def _matches_exclusion(relative: str) -> str | None:
    for pattern, reason in _EXCLUSION_RE:
        if pattern.search(relative):
            return reason
    return None


def _matches_governed_front_matter(relative: str, root: Path) -> str | None:
    """A markdown file with explicit governed front matter is a real entity."""
    if not relative.endswith((".md", ".markdown")):
        return None
    path = root / relative
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:1200]
    except OSError:
        return None
    if not _SKILL_FRONTMATTER.search(head[:200]):
        return None
    if _GOVERNED_FRONTMATTER.search(head):
        return "skill"
    return None


def assess_entity_worthiness(
    root: Path, relative: str, kind: str, *, surface: str
) -> ExclusionDecision:
    """Decide whether one file is a canonical semantic entity.

    Structural surfaces (code, contracts, policies) are admitted by nature.
    Documentation and provider prose must earn admission.
    """
    root = Path(root)
    excluded = _matches_exclusion(relative)
    if excluded:
        return ExclusionDecision(relative, False, excluded)

    if surface not in {"providers", "governance", "registry"}:
        return ExclusionDecision(relative, True, f"{surface}-surface-structural-entity")

    if kind in {"documentation"}:
        governed = _matches_governed_front_matter(relative, root)
        if governed:
            return ExclusionDecision(relative, True, "governed-front-matter", governed)
        for predicate, needles in WORTHY_PREDICATES.items():
            lowered = relative.lower()
            if any(needle in lowered for needle in needles):
                return ExclusionDecision(relative, True, f"{predicate}-predicate", predicate)
        return ExclusionDecision(
            relative, False, "unprovenanced-prose-not-canonical-entity"
        )

    if kind in {"agent", "registry", "manifest", "orchestration", "contract", "policy"}:
        return ExclusionDecision(relative, True, f"{kind}-is-structural-entity")
    return ExclusionDecision(relative, True, f"{surface}-surface-entity")


def build_exclusion_ledger(
    decisions: Iterable[ExclusionDecision],
) -> dict[str, object]:
    rows = [decision for decision in decisions]
    excluded = [decision for decision in rows if not decision.admitted]
    reasons = Counter(decision.reason for decision in excluded)
    return {
        "schema_version": EXCLUSION_SCHEMA,
        "assessed": len(rows),
        "admitted": len(rows) - len(excluded),
        "excluded": len(excluded),
        "exclusion_reasons": dict(reasons.most_common()),
        "excluded_paths": [decision.path for decision in excluded[:400]],
        "admitted_paths_sample": [
            decision.path for decision in rows if decision.admitted
        ][:200],
    }