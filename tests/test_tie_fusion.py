"""Object-local T.I.E. experience fusion.

`model_group_preparation` always imported `fuse_tie_experience` lazily, but the
function did not exist, so no test could reach the T.I.E. path and any real
caller received a bare ImportError from inside plan compilation.

These tests drive the real owner end to end: experience is recorded through
`record_observation`, then fused, and the result is checked for determinism,
honest reporting of unavailable subjects, and the absence of any authority or
write-back.
"""
import json

import pytest

from runtime import usage_memory as um


def _record(root, count=3):
    for index in range(count):
        um.record_observation(
            root,
            "workflow",
            "wf_probe",
            {
                "outcome": "success" if index else "partial",
                "disposition": "NO_PRODUCT_DEFECT",
                "run_id": f"run-{index}",
                "correlation_id": f"effect-{index}",
                "duration_ms": 100 + index,
                "tokens": 10 * index,
                "success_criteria_met": True,
                "gap": None if index else "first attempt missed a boundary",
            },
        )


@pytest.fixture()
def project(tmp_path):
    (tmp_path / "orchestration" / "workflows").mkdir(parents=True)
    return tmp_path


def test_fuses_recorded_experience_with_attributed_lineage(project):
    _record(project)
    fused = um.fuse_tie_experience(project, ({"kind": "workflow", "identity": "wf_probe"},))
    subject = fused["subjects"][0]
    assert subject["state"] == "available"
    assert subject["lineage_status"] == "ATTRIBUTED"
    assert subject["returned_record_count"] == 3
    assert all(row["run_id"] for row in subject["records"])
    assert subject["experience_log_sha256"]


def test_fusion_is_deterministic_and_grants_no_authority(project):
    _record(project)
    binding = {"kind": "workflow", "identity": "wf_probe", "version": "1.0.0"}
    first = um.fuse_tie_experience(project, (binding,))
    second = um.fuse_tie_experience(project, (binding,))
    assert first["fusion_sha256"] == second["fusion_sha256"]
    assert first["authority_granted"] is False
    assert first["propagated"] is False


def test_fusion_is_read_only(project):
    _record(project)
    log = project / "orchestration/workflows/wf_probe/memory/usage.jsonl"
    before = log.read_bytes()
    um.fuse_tie_experience(project, ({"kind": "workflow", "identity": "wf_probe"},))
    assert log.read_bytes() == before
    assert len(list(project.rglob("usage.jsonl"))) == 1


def test_subject_without_experience_is_reported_not_invented(project):
    (project / "orchestration" / "workflows" / "wf_empty").mkdir(parents=True)
    fused = um.fuse_tie_experience(project, ({"kind": "workflow", "identity": "wf_empty"},))
    subject = fused["subjects"][0]
    assert subject["state"] == "available"
    assert subject["lineage_status"] == "NO_EXPERIENCE"
    assert subject["records"] == []


def test_unavailable_subject_is_reported_with_its_failure(project):
    fused = um.fuse_tie_experience(project, ({"kind": "agent", "identity": "agt_absent"},))
    subject = fused["subjects"][0]
    assert subject["state"] == "corrupt_or_unavailable"
    assert subject["failure_type"]
    assert subject["records"] == []


@pytest.mark.parametrize(
    "binding",
    [
        {"kind": "workflow"},
        {"kind": "workflow", "identity": "wf", "extra": 1},
        {"kind": "", "identity": "wf"},
        {"kind": "workflow", "identity": "wf", "version": ""},
        "not-a-mapping",
    ],
)
def test_malformed_bindings_are_refused(project, binding):
    with pytest.raises(ValueError):
        um.fuse_tie_experience(project, (binding,))


def test_unknown_subject_kind_is_refused(project):
    with pytest.raises(ValueError, match="unknown experience subject kind"):
        um.fuse_tie_experience(project, ({"kind": "galaxy", "identity": "x"},))


def test_binding_count_is_bounded(project):
    bindings = tuple({"kind": "workflow", "identity": f"wf_{i}"} for i in range(5))
    with pytest.raises(ValueError, match="at most"):
        um.fuse_tie_experience(project, bindings)


def test_corrupt_log_line_is_surfaced_not_dropped(project):
    log = project / "orchestration/workflows/wf_bad/memory/usage.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text('{"not": "a valid record"}\n', encoding="utf-8")
    fused = um.fuse_tie_experience(project, ({"kind": "workflow", "identity": "wf_bad"},))
    subject = fused["subjects"][0]
    assert subject["lineage_status"] == "LEGACY_EFFECT_LINEAGE_UNAVAILABLE"
    assert subject["record_count"] >= 1


def test_linked_experience_log_is_refused(project):
    """A log reachable through a link must be reported, not read.

    The experience log is append-only evidence; reading it through a symlink or
    junction would let unrelated bytes be presented as a subject's history.
    """
    victim = project / "outside.txt"
    victim.write_text('{"outcome": "success", "run_id": "forged"}\n', encoding="utf-8")
    log = project / "orchestration/workflows/wf_linked/memory/usage.jsonl"
    log.parent.mkdir(parents=True)
    try:
        log.symlink_to(victim)
    except (OSError, NotImplementedError):
        pytest.skip("host cannot create symlinks for this check")
    fused = um.fuse_tie_experience(project, ({"kind": "workflow", "identity": "wf_linked"},))
    subject = fused["subjects"][0]
    assert subject["state"] == "corrupt_or_unavailable"
    assert subject["records"] == []


def test_two_field_binding_is_accepted(project):
    """Callers may bind without a version; the fusion must not require one."""
    _record(project, count=1)
    fused = um.fuse_tie_experience(project, ({"kind": "workflow", "identity": "wf_probe"},))
    assert fused["subjects"][0]["state"] == "available"


def test_fusion_digest_changes_when_experience_changes(project):
    _record(project, count=1)
    first = um.fuse_tie_experience(project, ({"kind": "workflow", "identity": "wf_probe"},))
    _record(project, count=2)
    second = um.fuse_tie_experience(project, ({"kind": "workflow", "identity": "wf_probe"},))
    assert first["fusion_sha256"] != second["fusion_sha256"]
    assert json.dumps(second, sort_keys=True) != json.dumps(first, sort_keys=True)
