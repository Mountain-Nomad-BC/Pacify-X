from __future__ import annotations

from pathlib import Path

from scripts.build_reclamation_learning_promotion import build


ROOT = Path(__file__).resolve().parents[1]


def test_real_cleanup_evidence_promotes_a_reversible_process_revision() -> None:
    result = build(ROOT)
    assert result["valid"] is True
    assert result["evidence_denominator"]["failed_incumbent_receipts"] >= 2
    assert result["evidence_denominator"]["successful_challenger_receipts"] >= 6
    assert result["confidence"]["passed"] is True
    assert result["comparison"]["passed"] is True
    assert result["research"]["passed"] is True
    assert result["promotion"]["passed"] is True
    assert result["promotion"]["learning_direct_write_allowed"] is False
    assert result["rollback"]["available"] is True
    assert result["decay"]["next_state"] == "canonical"
