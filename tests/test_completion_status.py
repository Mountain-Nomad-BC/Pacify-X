from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts.build_completion_status import build, write
from runtime.test_profiles import group_status, section_status


ROOT = Path(__file__).resolve().parents[1]


def test_generated_completion_status_is_current_and_does_not_overclaim() -> None:
    generated = build(ROOT)
    stored = json.loads((ROOT / "registry/completion_status.json").read_text(encoding="utf-8"))
    surface = json.loads(
        (ROOT / "registry/operational_surface_audit_20260816.json").read_text(
            encoding="utf-8"
        )
    )["findings"]
    instruction = json.loads(
        (ROOT / "registry/instruction_reconciliation_audit_20260816.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored == generated
    assert generated["schema_version"] == "px.completion-status/1.3"
    assert generated["historical_cards_complete"] is True
    assert generated["cards_complete"] is False
    assert generated["operationally_complete"] is False
    assert generated["complete"] is False
    assert generated["certified"] is False
    assert generated["universal_cards"]["counts"] == {"accepted": 81}
    assert generated["universal_cards"]["open_ids"] == []
    assert generated["adversarial_repairs"]["counts"] == {"accepted": 26}
    assert generated["adversarial_repairs"]["open_ids"] == []
    assert generated["current_adversarial_reaudit"]["count"] == 34
    assert generated["current_adversarial_reaudit"]["status_counts"] == {
        "fixed_pending_independent_verification": 34
    }
    assert generated["current_adversarial_reaudit"]["open_ids"] == []
    assert len(generated["current_adversarial_reaudit"]["pending_ids"]) == 34
    assert generated["current_functional_validation"]["count"] == 5
    assert generated["current_functional_validation"]["status_counts"] == {
        "accepted": 2,
        "fixed_pending_independent_verification": 2,
        "improved_residual_debt": 1,
    }
    assert generated["current_functional_validation"]["open_ids"] == []
    assert len(generated["current_functional_validation"]["pending_ids"]) == 3
    assert generated["current_operational_validation"]["count"] == 2
    assert generated["current_operational_validation"]["status_counts"] == {
        "fixed_pending_independent_verification": 2
    }
    assert generated["current_operational_validation"]["open_ids"] == []
    assert len(generated["current_operational_validation"]["pending_ids"]) == 2
    assert generated["current_independent_operational_audit_r1"]["count"] == 5
    assert generated["current_independent_operational_audit_r1"]["status_counts"] == {
        "fixed_pending_independent_verification": 5
    }
    assert len(
        generated["current_independent_operational_audit_r1"]["pending_ids"]
    ) == 5
    assert generated["current_instruction_reconciliation"]["count"] == len(
        instruction["requirements"]
    )
    assert generated["current_instruction_reconciliation"]["complete"] is False
    expected_counts = Counter(row["status"] for row in surface)
    assert generated["current_operational_surface_audit"]["count"] == len(surface)
    assert generated["current_operational_surface_audit"]["status_counts"] == dict(
        sorted(expected_counts.items())
    )
    assert generated["operational_readiness"]["open_ids"] == [
        row["id"] for row in surface if row["status"] == "open"
    ]
    assert generated["live_verification"]["pending_ids"] == [
        row["id"]
        for row in surface
        if row["status"]
        in {
            "fixed_pending_live_verification",
            "fixed_pending_live_reload_verification",
        }
    ]
    assert generated["operational_readiness"]["repairs_complete"] is False
    assert generated["live_verification"]["complete"] is False
    assert generated["certification_freshness"]["fresh"] is False
    assert any(
        "product-surface audit" in reason
        for reason in generated["blocking_reasons"]
    )
    assert generated["current_gates"]["valid"] is (
        section_status(ROOT)["valid"] and group_status(ROOT)["valid"]
    )
    assert generated["blocking_reasons"]


def test_completion_projection_writer_is_atomic_and_exact() -> None:
    target = ROOT / "registry/completion_status.json"
    before = target.read_bytes()
    try:
        written = write(ROOT)
        assert json.loads(target.read_text(encoding="utf-8")) == written
        assert not target.with_name(f".{target.name}.prepared").exists()
    finally:
        target.write_bytes(before)
