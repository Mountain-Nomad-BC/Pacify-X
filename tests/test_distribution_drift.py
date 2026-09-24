from __future__ import annotations

import math
import pytest

from runtime.cognitive_assurance import operational_assurance_evidence
from runtime.distribution_drift import assess_distribution_drift, jensen_shannon_divergence, population_stability_index
from runtime.learning_promotion import operational_evidence_candidate


def test_drift_metrics_are_deterministic_and_bounded() -> None:
    psi = population_stability_index((90, 10), (60, 40))
    jsd = jensen_shannon_divergence((90, 10), (60, 40))
    assert psi > 0
    assert 0 <= jsd <= 1
    finding = assess_distribution_drift("route-share", (90, 10), (60, 40), psi_warn=0.005, psi_high=0.01)
    assert finding.severity == "high"
    assert finding.propose_learning_candidate is True
    assert finding.authority_granted is False
    assert len(finding.evidence_sha256) == 64


def test_invalid_distribution_fails_closed() -> None:
    with pytest.raises(ValueError, match="positive total mass"):
        population_stability_index((0, 0), (1, 0))
    with pytest.raises(ValueError, match="finite"):
        jensen_shannon_divergence((1, math.nan), (1, 2))


def test_drift_enters_assurance_and_learning_as_evidence_only() -> None:
    finding = assess_distribution_drift("retrieval", (1, 9), (9, 1), psi_warn=0.005, psi_high=0.01)
    assurance = operational_assurance_evidence(drift_findings=(finding,), component_health={"reranker": "degraded"})
    assert assurance["decision"] == "review"
    assert assurance["authority_granted"] is False
    candidate = operational_evidence_candidate(evidence_type="drift", evidence_sha256=finding.evidence_sha256, source_revision="retrieval-v7", severity=finding.severity, reasons=("distribution shifted",))
    assert candidate["canonical"] is False
    assert candidate["promotion_required"] is True
