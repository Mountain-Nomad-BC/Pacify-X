from __future__ import annotations

import json
from pathlib import Path
import shutil

from scripts.build_reclamation_learning_promotion import build


ROOT = Path(__file__).resolve().parents[1]


def _portable_cleanup_evidence(tmp_path: Path) -> Path:
    for relative in (
        ".px/skills/manage-resource-lifecycle/references/lifecycle-policy.md",
        "runtime/resource_lifecycle.py",
        "registry/adversarial_reaudit_20260813.json",
        ".engineering-bootstrap/test-evidence/sections/testing-governance.json",
    ):
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    receipts = (
        tmp_path
        / ".engineering-bootstrap"
        / "resource-lifecycle"
        / "cleanup-receipts"
    )
    receipts.mkdir(parents=True)
    for index in range(2):
        (receipts / f"cleanup-failed-{index}.json").write_text(
            json.dumps(
                {
                    "lane_id": "group:release-build",
                    "resources_failed": 1,
                    "resources_reclaimed": 0,
                    "errors": ["synthetic transient lock"],
                    "bytes_reclaimed": 0,
                    "end_time": f"2026-08-13T00:00:0{index}Z",
                }
            ),
            encoding="utf-8",
        )
    for index in range(6):
        (receipts / f"cleanup-passed-{index}.json").write_text(
            json.dumps(
                {
                    "lane_id": "group:derived-integrity",
                    "resources_failed": 0,
                    "resources_reclaimed": 1,
                    "errors": [],
                    "bytes_reclaimed": index + 1,
                    "end_time": f"2026-08-13T00:01:0{index}Z",
                }
            ),
            encoding="utf-8",
        )
    return tmp_path


def test_bounded_cleanup_evidence_promotes_a_reversible_process_revision(
    tmp_path: Path,
) -> None:
    result = build(_portable_cleanup_evidence(tmp_path))
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
