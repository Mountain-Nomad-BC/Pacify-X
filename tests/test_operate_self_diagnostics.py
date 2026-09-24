"""Tests for the Self Operations diagnostic coordinator.

V3 requires this as the one intentional new capability, and it must be a **composition layer**.
These tests pin the properties that keep it from becoming a second optimizer:

  * `NO_PRODUCT_DEFECT` and `PROBE_OR_TEST_DEFECT` are reachable outcomes;
  * an environment/probe/evidence condition is never escalated into a product defect;
  * the coordinator has no mutation path and never self-approves;
  * every classification binds to a canonical owner or reports an explicit miss.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

import runtime.self_diagnostics as coordinator  # noqa: E402
from runtime.self_diagnostics import (  # noqa: E402
    DISPOSITIONS,
    OWNER_BY_DISPOSITION,
    STOP_CONDITIONS,
    classify_condition,
    diagnose,
    select_specialist,
)


def _signals(*specs):
    return [{"signal": signal, "scope": scope} for signal, scope in specs]


# ---------------------------------------------------------------------------
# Non-repair dispositions must be reachable
# ---------------------------------------------------------------------------


def test_no_product_defect_is_reachable() -> None:
    result = classify_condition(
        _signals(("nothing_wrong_observed", "runtime/models.py"))
    )
    assert result.disposition == "NO_PRODUCT_DEFECT"
    assert result.canonical_owner is None


@pytest.mark.parametrize(
    "signal,disposition",
    [
        ("probe_defect", "PROBE_OR_TEST_DEFECT"),
        ("test_defect", "PROBE_OR_TEST_DEFECT"),
        ("environment_unavailable", "ENVIRONMENT_UNAVAILABLE"),
        ("offline", "EXPECTED_OFFLINE_BOUNDARY"),
        ("authority_denied", "AUTHORITY_DENIED"),
        ("evidence_stale", "EVIDENCE_STALE_OR_INVALID"),
        ("configuration_error", "CONFIGURATION_DEFECT"),
        ("generated_stale", "GENERATED_STATE_DEFECT"),
    ],
)
def test_non_repair_signals_classify_as_themselves(
    signal: str, disposition: str
) -> None:
    result = classify_condition(_signals((signal, "some/scope")))
    assert result.disposition == disposition
    assert result.competing_explanation, "a competing explanation must be recorded"


def test_environment_condition_is_never_a_product_defect() -> None:
    # Even alongside a behaviour signal, the non-repair signal outranks it.
    result = classify_condition(
        _signals(
            ("behaviour_incorrect", "runtime/x.py"),
            ("environment_unavailable", "runtime/x.py"),
        )
    )
    assert result.disposition == "ENVIRONMENT_UNAVAILABLE"
    assert result.disposition != "PRODUCT_DEFECT"


def test_unevidenced_failure_is_not_treated_as_success_or_defect() -> None:
    # A failed check with no evidence is uninterpretable: stale/ambiguous evidence, not a defect.
    result = classify_condition(
        [
            {
                "signal": "check_failed",
                "scope": "tests/test_x.py",
                "evidence_ref": None,
            },
        ]
    )
    assert result.disposition == "EVIDENCE_STALE_OR_INVALID"
    assert "not interpretable" in result.reason or "no usable evidence" in result.reason


def test_stale_evidence_beyond_the_bound_is_classified_stale() -> None:
    result = classify_condition(
        [
            {
                "signal": "check_passed",
                "scope": "s",
                "evidence_ref": "e1",
                "evidence_age_seconds": 999999.0,
            }
        ],
        evidence_max_age_seconds=3600.0,
    )
    assert result.disposition == "EVIDENCE_STALE_OR_INVALID"
    assert "freshness bound" in result.reason


def test_fresh_evidence_passes_the_bound() -> None:
    result = classify_condition(
        [
            {
                "signal": "slow",
                "scope": "s",
                "evidence_ref": "e1",
                "evidence_age_seconds": 10.0,
            }
        ],
        evidence_max_age_seconds=3600.0,
    )
    assert result.disposition == "OPTIMIZATION_OPPORTUNITY"


# ---------------------------------------------------------------------------
# Repair dispositions
# ---------------------------------------------------------------------------


def test_unwired_seam_is_an_integration_defect_not_a_product_defect() -> None:
    result = classify_condition(
        _signals(("unwired_seam", "runtime/a.py -> runtime/b.py"))
    )
    assert result.disposition == "INTEGRATION_DEFECT"
    assert "owners exist" in result.reason


def test_behaviour_failure_is_a_product_defect_only_after_exclusions() -> None:
    result = classify_condition(_signals(("behaviour_incorrect", "runtime/a.py")))
    assert result.disposition == "PRODUCT_DEFECT"
    assert "excluded" in (result.competing_explanation or "")


def test_slow_behaviour_is_an_optimization_opportunity_not_a_defect() -> None:
    assert (
        classify_condition(_signals(("slow", "s"))).disposition
        == "OPTIMIZATION_OPPORTUNITY"
    )


# ---------------------------------------------------------------------------
# No mutation, no self-approval
# ---------------------------------------------------------------------------


def test_coordinator_has_no_write_path() -> None:
    source = inspect.getsource(coordinator)
    # No filesystem write, no process spawn, no subprocess anywhere in the module.
    for forbidden in (
        "open(",
        "write_text",
        "os.replace",
        "shutil",
        "subprocess",
        "Popen",
        "os.remove",
        "unlink",
    ):
        assert forbidden not in source, f"coordinator must not contain {forbidden!r}"


def test_diagnosis_never_permits_self_execution() -> None:
    result = diagnose(
        ROOT,
        condition="reported",
        scope="s",
        signals=_signals(("behaviour_incorrect", "s")),
    )
    assert result.coordinator_may_execute is False
    assert result.requires_authority is True


def test_non_repair_diagnosis_requires_no_authority() -> None:
    result = diagnose(
        ROOT,
        condition="reported",
        scope="s",
        signals=_signals(("environment_unavailable", "s")),
    )
    assert result.requires_authority is False
    assert result.coordinator_may_execute is False


def test_diagnosis_is_deterministic() -> None:
    first = diagnose(ROOT, condition="c", scope="s", signals=_signals(("slow", "s")))
    second = diagnose(ROOT, condition="c", scope="s", signals=_signals(("slow", "s")))
    assert first.diagnosis_sha256 == second.diagnosis_sha256


def test_recursion_controls_are_declared() -> None:
    result = diagnose(ROOT, condition="c", scope="s", signals=_signals(("slow", "s")))
    assert set(result.stop_conditions) == set(STOP_CONDITIONS)
    assert "fixed_point" in result.stop_conditions
    assert "max_mutation_transactions" in result.stop_conditions


# ---------------------------------------------------------------------------
# Owner binding
# ---------------------------------------------------------------------------


def test_every_disposition_declares_an_owner_or_explicitly_none() -> None:
    assert set(OWNER_BY_DISPOSITION) == set(DISPOSITIONS)
    for disposition in DISPOSITIONS:
        result = select_specialist(ROOT, disposition)
        assert result["may_create_owner"] is False
        assert "owner" in result or "owner_class" in result


def test_non_repair_dispositions_require_no_owner() -> None:
    for disposition in (
        "NO_PRODUCT_DEFECT",
        "ENVIRONMENT_UNAVAILABLE",
        "EXPECTED_OFFLINE_BOUNDARY",
        "AUTHORITY_DENIED",
    ):
        result = select_specialist(ROOT, disposition)
        assert result["owner"] is None
        assert "not a repair" in result["reason"]


def test_specialist_binding_forbids_creating_a_second_owner() -> None:
    result = select_specialist(ROOT, "PRODUCT_DEFECT")
    assert result["may_create_owner"] is False
    assert result["declared_owners_available"] > 100


def test_unknown_disposition_is_rejected() -> None:
    with pytest.raises(ValueError):
        select_specialist(ROOT, "TOTALLY_MADE_UP")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_empty_signals_are_rejected() -> None:
    with pytest.raises(ValueError):
        classify_condition([])


def test_too_many_signals_are_rejected() -> None:
    with pytest.raises(ValueError):
        classify_condition([{"signal": "slow", "scope": "s"}] * 40)


def test_invalid_evidence_age_is_rejected() -> None:
    with pytest.raises(ValueError):
        classify_condition(
            [{"signal": "slow", "scope": "s", "evidence_age_seconds": -1.0}]
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_coordinator_is_admitted_and_registered() -> None:
    ledger = json.loads(
        (ROOT / "registry/admission_ledger.json").read_text(encoding="utf-8-sig")
    )
    record = next(
        (r for r in ledger["records"] if r["id"] == "operate-self-diagnostics"), None
    )
    assert record is not None and record["status"] == "active"

    capability_map = json.loads(
        (ROOT / "registry/capability_map.json").read_text(encoding="utf-8")
    )
    ids = {entry["id"] for entry in capability_map["active_capabilities"]}
    assert "operate-self-diagnostics" in ids


def test_coordinator_native_package_is_complete() -> None:
    target = ROOT / ".px/skills/operate-self-diagnostics"
    for name in ("SKILL.md", "capability.json", "skill.yaml"):
        assert (target / name).is_file(), f"missing {name}"
    for sub in ("agents", "contracts", "resources", "tests"):
        assert (target / sub).is_dir(), f"missing {sub}/"


def test_coordinator_is_visible_to_the_librarian() -> None:
    from runtime.registry import skill_navigation_index

    ids = {getattr(i, "capability_id", str(i)) for i in skill_navigation_index(ROOT)}
    assert "operate-self-diagnostics" in ids
