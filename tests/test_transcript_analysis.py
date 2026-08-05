from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from runtime.cli import main
from runtime.transcript_analysis import (
    build_queue_adapter_plan,
    default_profile,
    export_selected_summary,
    ingest_transcripts,
    normalize_queue_term,
    validate_canonical_record,
    validate_run,
    validate_transcript_orchestration,
    write_canonical_records,
)


ROOT = Path(__file__).resolve().parents[1]


def _record(source: dict[str, object], **updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "record_id": "rec-001",
        "record_kind": "issue",
        "queue_id": "queue-a",
        "conversation_id": source["conversation_id"],
        "source_id": source["source_id"],
        "source_sha256": source["source_sha256"],
        "source_span": {"start_line": 1, "end_line": 1},
        "lifecycle_state": "ACTIVE_CALL",
        "evidence_state": "ASSERTED",
        "action_state": "NONE",
        "outcome_state": "NONE",
        "label": "reported symptom",
        "text": "The caller reported a symptom.",
        "value": None,
        "unit": None,
        "validation_evidence": [],
        "review_required": False,
    }
    record.update(updates)
    return record


def _run(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source = tmp_path / "conversation-001.txt"
    source.write_text(
        "Caller reports a problem.\nAgent recommends inspection.\n", encoding="utf-8"
    )
    output = tmp_path / "output"
    result = ingest_transcripts(
        ROOT,
        [source],
        output,
        queue_id="queue-a",
        run_id="run-001",
        source_dates={source.name: "2026-08-04"},
        apply=True,
    )
    return Path(result["target"]), result["sources"][0]


def test_default_profile_is_portable_and_never_publishes_latest() -> None:
    profile = default_profile("queue-a")
    assert profile["tool_root"] is None
    assert profile["runner"] is None
    assert profile["publish_latest"] is False
    plan = build_queue_adapter_plan(profile, ROOT, ROOT / "future-run")
    assert plan["command"] is None
    assert plan["execution_authorized"] is False


def test_external_adapter_plan_is_contained_and_never_executes(tmp_path: Path) -> None:
    tool = tmp_path / "tool"
    tool.mkdir()
    runner = tool / "run.py"
    runner.write_text("print('adapter')\n", encoding="utf-8")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    profile = {
        **default_profile("queue-a"),
        "adapter": "external-command",
        "tool_root": str(tool),
        "runner": "run.py",
    }
    plan = build_queue_adapter_plan(profile, inputs, tmp_path / "new-run")
    assert plan["shell"] is False
    assert plan["execution_authorized"] is False
    assert plan["runner_sha256"]
    with pytest.raises(ValueError, match="relative"):
        build_queue_adapter_plan(
            {**profile, "runner": str(runner.resolve())}, inputs, tmp_path / "other-run"
        )


def test_ingest_is_dry_run_first_immutable_and_does_not_touch_latest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "conversation-001.txt"
    source.write_text("source transcript", encoding="utf-8")
    output = tmp_path / "output"
    planned = ingest_transcripts(
        ROOT, [source], output, queue_id="queue-a", run_id="targeted-001"
    )
    assert planned["applied"] is False
    assert not Path(planned["target"]).exists()
    applied = ingest_transcripts(
        ROOT, [source], output, queue_id="queue-a", run_id="targeted-001", apply=True
    )
    run = Path(applied["target"])
    assert (
        run / "sources" / "00001-conversation-001.txt"
    ).read_bytes() == source.read_bytes()
    assert not (output / "queue-a" / "latest").exists()
    with pytest.raises(FileExistsError):
        ingest_transcripts(
            ROOT,
            [source],
            output,
            queue_id="queue-a",
            run_id="targeted-001",
            apply=True,
        )


def test_recommendation_cannot_be_mislabeled_as_verified_repair() -> None:
    source = {
        "conversation_id": "conversation-001",
        "source_id": "src-" + "a" * 20,
        "source_sha256": "a" * 64,
    }
    record = _record(
        source,
        record_kind="action",
        action_state="RECOMMENDED",
        outcome_state="VERIFIED",
        validation_evidence=["operator says done"],
    )
    with pytest.raises(ValueError, match="cannot be a verified outcome"):
        validate_canonical_record(ROOT, record)


def test_verified_outcome_requires_asserted_validation_evidence() -> None:
    source = {
        "conversation_id": "conversation-001",
        "source_id": "src-" + "a" * 20,
        "source_sha256": "a" * 64,
    }
    record = _record(
        source,
        record_kind="outcome",
        outcome_state="VERIFIED",
        evidence_state="UNCERTAIN",
        review_required=True,
    )
    with pytest.raises(ValueError, match="requires asserted evidence"):
        validate_canonical_record(ROOT, record)


def test_queue_ontology_cannot_leak_without_review() -> None:
    ontology = {
        "schema_version": "1.0",
        "queue_id": "queue-a",
        "version": "1",
        "aliases": {"pump": "circulation-pump"},
        "components": ["circulation-pump"],
        "alerts": [],
        "thresholds": {},
        "flow_policies": [],
        "reviewed_transfers": [],
    }
    assert (
        normalize_queue_term(ontology, queue_id="queue-a", term="pump")
        == "circulation-pump"
    )
    with pytest.raises(ValueError, match="explicit reviewed transfer"):
        normalize_queue_term(
            ontology, queue_id="queue-a", term="pump", from_queue="queue-b"
        )
    with pytest.raises(ValueError, match="owned by another queue"):
        normalize_queue_term(ontology, queue_id="queue-b", term="pump")


def test_records_trace_to_source_and_export_deterministically(tmp_path: Path) -> None:
    run, source = _run(tmp_path)
    records = [
        _record(source),
        _record(
            source,
            record_id="rec-002",
            record_kind="action",
            action_state="RECOMMENDED",
            label="inspect",
            text="Inspect the component.",
        ),
        _record(
            source,
            record_id="rec-003",
            record_kind="outcome",
            outcome_state="REPORTED",
            label="caller report",
            text="Caller reported improvement.",
        ),
    ]
    written = write_canonical_records(ROOT, run, records, apply=True)
    assert written["record_count"] == 3
    validation = validate_run(ROOT, run)
    assert validation["valid"], validation["errors"]
    first = export_selected_summary(
        ROOT, run, [str(source["conversation_id"])], tmp_path / "summary.csv"
    )
    second = export_selected_summary(
        ROOT, run, [str(source["conversation_id"])], tmp_path / "summary-2.csv"
    )
    assert first["sha256"] == second["sha256"]
    assert "action or recommendation documented; outcome unconfirmed" in first["csv"]
    assert str(source["source_sha256"]) in first["csv"]


def test_record_source_and_queue_mismatch_fail_closed(tmp_path: Path) -> None:
    run, source = _run(tmp_path)
    bad = _record(source, queue_id="queue-b")
    with pytest.raises(ValueError, match="queue boundary mismatch"):
        write_canonical_records(ROOT, run, [bad], apply=True)


def test_run_detects_source_tampering(tmp_path: Path) -> None:
    run, _ = _run(tmp_path)
    (run / "sources" / "00001-conversation-001.txt").write_text(
        "tampered", encoding="utf-8"
    )
    result = validate_run(ROOT, run)
    assert result["valid"] is False
    assert any("source copy integrity mismatch" in error for error in result["errors"])


def test_transcript_cli_and_orchestration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert validate_transcript_orchestration(ROOT)["valid"]
    source = tmp_path / "conversation-001.txt"
    source.write_text("transcript", encoding="utf-8")
    code = main(
        [
            "--root",
            str(ROOT),
            "transcripts",
            "ingest",
            "--input",
            str(source),
            "--output-root",
            str(tmp_path / "out"),
            "--queue-id",
            "queue-a",
            "--run-id",
            "cli-run",
        ]
    )
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["applied"] is False
    assert output["publish_latest"] is False


def test_transcript_export_skill_script_executes_directly(tmp_path: Path) -> None:
    run, source = _run(tmp_path)
    write_canonical_records(ROOT, run, [_record(source)], apply=True)
    script = (
        ROOT / ".agents/skills/transcript-analysis/scripts/export_transcript_summary.py"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(ROOT),
            "--run",
            str(run),
            "--conversation-id",
            str(source["conversation_id"]),
            "--output",
            str(tmp_path / "summary.csv"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["row_count"] == 1
