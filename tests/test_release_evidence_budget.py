from pathlib import Path

from runtime.release_preflight import evidence_budget


def test_evidence_amplification_budget_fails_before_finalizer(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"; evidence.mkdir(); (evidence / "coverage.json").write_bytes(b"x" * 101)
    result = evidence_budget(tmp_path, {"max_total_release_evidence_bytes": 1000, "max_single_evidence_file_bytes": 100})
    assert not result["valid"]
    assert result["failures"][0]["code"] == "RP-EVD-002"


def test_bounded_evidence_passes(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"; evidence.mkdir(); (evidence / "summary.json").write_text("{}")
    assert evidence_budget(tmp_path, {"max_total_release_evidence_bytes": 100, "max_single_evidence_file_bytes": 100})["valid"]
