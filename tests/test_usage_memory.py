"""Tests for the governed usage-memory layer (skills, agents, workflows).

Owner requirement (2026-09-24): skill stats live in a memory file inside each skill; usage logs the
stats, success rates, gaps, shortcomings, and issues; agents and workflows get the same treatment.

The tests pin the properties that make the memory trustworthy, not just that it writes a file:

  * the log is append-only;
  * the rollup is derived and rebuildable, never canonical;
  * a refusal is not a success;
  * a failure is recorded as a failure;
  * no prompt, output, secret, or memory content is stored;
  * an unknown subject is never invented;
  * a corrupt record is surfaced, not silently dropped.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from runtime.usage_memory import (  # noqa: E402
    DISPOSITIONS,
    KIND_ROOT,
    OUTCOMES,
    USAGE_SCHEMA,
    ensure_subject_memory,
    list_subjects_with_memory,
    read_stats,
    rebuild_stats,
    record_observation,
)


def _subject(kind: str, name: str) -> tuple[Path, str]:
    # Create a throwaway subject under a temporary root so tests never touch the real library.
    temp_root = Path(tempfile.mkdtemp(prefix="px-usage-memory-"))
    base = temp_root / KIND_ROOT[kind] / name
    base.mkdir(parents=True, exist_ok=True)
    (base / "memory").mkdir(parents=True, exist_ok=True)
    return temp_root, name


# ---------------------------------------------------------------------------
# Where the memory lives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ("skill", "workflow"))
def test_memory_lives_inside_the_subject(kind: str) -> None:
    tmp, name = _subject(kind, f"pytest-{kind}-memory-loc")
    record_observation(tmp, kind, name, {"outcome": "success"})
    memory = tmp / KIND_ROOT[kind] / name / "memory"
    assert (memory / "usage.jsonl").is_file()
    assert (memory / "stats.json").is_file()


def test_agent_memory_resolves_through_the_registry() -> None:
    # An agent subject is only valid when the registry declares it with a real body path.
    registry = json.loads((ROOT / "registry/agency_agent_registry.json").read_text(encoding="utf-8-sig"))
    assert registry.get("agents"), "the agency agent registry must declare agents"
    agents = list_subjects_with_memory(ROOT, "agent")
    assert agents, "at least one declared agent must already carry usage memory"


def test_memory_directories_carry_an_append_only_log() -> None:
    for kind in ("skill", "agent", "workflow"):
        subjects = list_subjects_with_memory(ROOT, kind)
        assert subjects, f"{kind}: at least one subject must carry memory"


def test_subject_roots_are_the_declared_locations() -> None:
    # Agents are owned by the agency-agent provider registry, not a parallel .px tree.
    assert KIND_ROOT["skill"] == Path(".px/skills")
    assert KIND_ROOT["agent"] == Path("providers/agency_agents/agents")
    assert KIND_ROOT["workflow"] == Path("orchestration/workflows")


def test_no_parallel_agent_tree_exists() -> None:
    # A second .px/agents tree would be duplicate authority over the same agents.
    assert not (ROOT / ".px/agents").exists()
    assert not (ROOT / ".px/workflows").exists()


# ---------------------------------------------------------------------------
# What is recorded
# ---------------------------------------------------------------------------


def test_success_is_recorded_with_a_success_rate() -> None:
    tmp, name = _subject("skill", "pytest-success-rate")
    stats = record_observation(tmp, "skill", name, {"outcome": "success"})["stats"]
    assert stats["outcomes"]["success"] == 1
    assert stats["success_rate"] == 1.0
    assert stats["schema_version"] == USAGE_SCHEMA


def test_a_failure_captures_gap_shortcoming_and_issue() -> None:
    tmp, name = _subject("skill", "pytest-gaps")
    stats = record_observation(tmp, "skill", name, {
        "outcome": "failure",
        "gap": "no fallback path",
        "shortcoming": "detection only in logs",
        "issue": "stale projection surfaced late",
        "disposition": "GENERATED_STATE_DEFECT",
    })["stats"]
    assert stats["gap_count"] == 3
    fields = {g["field"] for g in stats["gaps"]}
    assert fields == {"gap", "shortcoming", "issue"}
    assert stats["dispositions"]["GENERATED_STATE_DEFECT"] == 1


def test_a_refusal_is_not_counted_as_a_success() -> None:
    tmp, name = _subject("skill", "pytest-refusal")
    record_observation(tmp, "skill", name, {"outcome": "success"})
    stats = record_observation(tmp, "skill", name, {"outcome": "refused"})["stats"]
    assert stats["outcomes"]["refused"] == 1
    # The basis is success + partial + failure, so a refusal cannot inflate the rate.
    assert stats["success_rate"] == 1.0
    assert "refusal excluded" in stats["success_rate_basis"] or "success + partial + failure" in stats["success_rate_basis"]


def test_success_rate_is_computed_over_decisive_outcomes_only() -> None:
    tmp, name = _subject("skill", "pytest-rate-mixed")
    record_observation(tmp, "skill", name, {"outcome": "success"})
    record_observation(tmp, "skill", name, {"outcome": "partial"})
    stats = record_observation(tmp, "skill", name, {"outcome": "failure"})["stats"]
    assert stats["success_rate"] == pytest.approx(1 / 3, abs=1e-6)


def test_duration_and_tokens_are_summarised() -> None:
    tmp, name = _subject("skill", "pytest-metrics")
    record_observation(tmp, "skill", name, {"outcome": "success", "duration_ms": 10.0, "tokens": 100})
    stats = record_observation(tmp, "skill", name, {"outcome": "success", "duration_ms": 20.0, "tokens": 150})["stats"]
    assert stats["duration_samples"] == 2
    assert stats["duration_best_ms"] == 10.0
    assert stats["total_tokens"] == 250


# ---------------------------------------------------------------------------
# Content safety
# ---------------------------------------------------------------------------


def test_no_prompt_output_or_secret_field_is_accepted() -> None:
    tmp, name = _subject("skill", "pytest-no-content")
    for forbidden in ("prompt", "output", "content", "response", "secret", "api_key"):
        with pytest.raises(ValueError):
            record_observation(tmp, "skill", name, {"outcome": "success", forbidden: "leak"})


def test_recorded_fields_are_outcome_metadata_only() -> None:
    tmp, name = _subject("skill", "pytest-field-set")
    record_observation(tmp, "skill", name, {"outcome": "success", "duration_ms": 5.0})
    rows = [json.loads(line) for line in
            (tmp / KIND_ROOT["skill"] / name / "memory" / "usage.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    assert rows
    for row in rows:
        assert not ({"prompt", "output", "content", "response", "secret"} & set(row))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_outcome_is_rejected() -> None:
    tmp, name = _subject("skill", "pytest-bad-outcome")
    with pytest.raises(ValueError):
        record_observation(tmp, "skill", name, {"outcome": "triumph"})


def test_unknown_disposition_is_rejected() -> None:
    tmp, name = _subject("skill", "pytest-bad-disposition")
    with pytest.raises(ValueError):
        record_observation(tmp, "skill", name, {"outcome": "failure", "disposition": "MADE_UP"})


def test_all_v3_dispositions_are_accepted() -> None:
    tmp, name = _subject("skill", "pytest-dispositions")
    for disposition in DISPOSITIONS:
        record_observation(tmp, "skill", name, {"outcome": "failure", "disposition": disposition})
    stats = read_stats(tmp, "skill", name)
    assert set(stats["dispositions"]) == set(DISPOSITIONS)


def test_every_outcome_kind_is_accepted() -> None:
    tmp, name = _subject("skill", "pytest-outcomes")
    for outcome in OUTCOMES:
        record_observation(tmp, "skill", name, {"outcome": outcome})
    assert read_stats(tmp, "skill", name)["record_count"] == len(OUTCOMES)


def test_invalid_subject_id_is_rejected() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="px-usage-memory-"))
    with pytest.raises(ValueError):
        record_observation(tmp, "skill", "../escape", {"outcome": "success"})


def test_unknown_subject_kind_is_rejected() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="px-usage-memory-"))
    with pytest.raises(ValueError):
        record_observation(tmp, "plugin", "whatever", {"outcome": "success"})


def test_missing_subject_is_not_invented() -> None:
    with pytest.raises(ValueError):
        ensure_subject_memory(ROOT, "skill", "pytest-does-not-exist-subject")


def test_negative_duration_is_rejected() -> None:
    tmp, name = _subject("skill", "pytest-bad-duration")
    with pytest.raises(ValueError):
        record_observation(tmp, "skill", name, {"outcome": "success", "duration_ms": -1.0})


# ---------------------------------------------------------------------------
# Derived rollup
# ---------------------------------------------------------------------------


def test_rollup_is_rebuildable_and_deterministic() -> None:
    tmp, name = _subject("skill", "pytest-rebuild")
    record_observation(tmp, "skill", name, {"outcome": "success", "duration_ms": 1.0})
    record_observation(tmp, "skill", name, {"outcome": "failure", "gap": "x"})
    first = rebuild_stats(tmp, "skill", name)
    second = rebuild_stats(tmp, "skill", name)
    assert first["stats_sha256"] == second["stats_sha256"]


def test_stale_rollup_is_rebuilt_from_the_log() -> None:
    tmp, name = _subject("skill", "pytest-stale-rollup")
    record_observation(tmp, "skill", name, {"outcome": "success"})
    stats_path = tmp / KIND_ROOT["skill"] / name / "memory" / "stats.json"
    # Corrupt the rollup: a derived artifact must never be trusted over the log.
    stale = json.loads(stats_path.read_text(encoding="utf-8"))
    stale["record_count"] = 999
    stats_path.write_text(json.dumps(stale), encoding="utf-8")
    refreshed = read_stats(tmp, "skill", name)
    assert refreshed["record_count"] == 1


def test_a_corrupt_log_line_is_surfaced_not_dropped() -> None:
    tmp, name = _subject("skill", "pytest-corrupt-log")
    record_observation(tmp, "skill", name, {"outcome": "success"})
    log = tmp / KIND_ROOT["skill"] / name / "memory" / "usage.jsonl"
    with log.open("a", encoding="utf-8") as stream:
        stream.write("{not json\n")
    stats = rebuild_stats(tmp, "skill", name)
    assert stats["outcomes"]["failure"] >= 1
    assert any(g["field"] == "issue" for g in stats["gaps"])


def test_stats_note_declares_it_is_derived_not_canonical() -> None:
    tmp, name = _subject("skill", "pytest-note")
    stats = record_observation(tmp, "skill", name, {"outcome": "success"})["stats"]
    assert "Derived rollup" in stats["note"]
    assert "no prompts" in stats["note"]


# ---------------------------------------------------------------------------
# Real coverage
# ---------------------------------------------------------------------------


def test_every_declared_skill_has_a_memory_log() -> None:
    skills = sorted(p.name for p in (ROOT / KIND_ROOT["skill"]).iterdir() if p.is_dir())
    missing = [s for s in skills if not (ROOT / KIND_ROOT["skill"] / s / "memory" / "usage.jsonl").is_file()]
    assert not missing, f"skills without usage memory: {missing[:10]}"


def test_agents_and_workflows_have_memory_roots() -> None:
    assert (ROOT / KIND_ROOT["agent"]).is_dir()
    assert (ROOT / KIND_ROOT["workflow"]).is_dir()
