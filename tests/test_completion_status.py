from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts.build_completion_status import build, write, write_runtime
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
    assert generated["schema_version"] == "px.completion-status/1.4"
    assert generated["historical_cards_complete"] is True
    assert generated["cards_complete"] is (
        generated["current_instruction_reconciliation"]["complete"]
        and generated["current_operational_surface_audit"]["complete"]
        and generated["current_operational_gap_ledger"]["complete"]
    )
    assert generated["operationally_complete"] is generated["cards_complete"]
    assert generated["complete"] is (not generated["blocking_reasons"])
    assert generated["certified"] is (
        generated["certification_freshness"]["fresh"]
        and generated["release_certificate"].get("valid") is True
    )
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
    assert generated["current_instruction_reconciliation"]["complete"] is bool(
        instruction.get("completion_claim", {}).get("complete")
    )
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
    assert generated["operational_readiness"]["repairs_complete"] is not any(
        row["status"] == "open" for row in surface
    )
    assert generated["live_verification"]["complete"] is not any(
        row["status"]
        in {
            "fixed_pending_live_verification",
            "fixed_pending_live_reload_verification",
        }
        for row in surface
    )
    assert any(
        "product-surface audit" in reason
        for reason in generated["blocking_reasons"]
    ) is bool(generated["current_operational_surface_audit"]["pending_ids"])
    assert generated["current_gates"]["valid"] is (
        section_status(ROOT)["valid"] and group_status(ROOT)["valid"]
    )
    assert generated["blocking_reasons"]
    assert generated["current_operational_gap_ledger"]["valid"] is True
    assert generated["current_operational_gap_ledger"]["complete"] is False
    assert "PX-OS-1065" in generated["current_operational_gap_ledger"][
        "critical_high_blocker_ids"
    ]
    assert generated["operationally_complete"] is False
    assert generated["projection_metadata"]["authority_level"] == (
        "non-certifying-current-state-projection"
    )


def test_completion_projection_writer_is_atomic_and_exact() -> None:
    target = ROOT / "registry/completion_status.json"
    before = target.read_bytes()
    try:
        written = write(ROOT)
        assert json.loads(target.read_text(encoding="utf-8")) == written
        assert not target.with_name(f".{target.name}.prepared").exists()
    finally:
        target.write_bytes(before)


def test_runtime_completion_projection_binds_exact_artifact_custody(
    tmp_path: Path,
) -> None:
    target = (
        ROOT
        / ".engineering-bootstrap"
        / "runtime-core"
        / "completion_status.json"
    )
    before = target.read_bytes() if target.is_file() else None
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    try:
        written = write_runtime(ROOT, artifact_dir=artifact_dir)
        stored = json.loads(target.read_text(encoding="utf-8"))
        assert stored == written
        assert stored["runtime_projection"]["artifact_dir"] == str(
            artifact_dir.resolve()
        )
        assert not target.with_name(f".{target.name}.prepared").exists()
    finally:
        if before is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(before)
