from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from runtime.cli import main
from runtime.contracts import validate_instance
from runtime.health_model import (
    DOMAINS,
    HealthModelError,
    assess_health_claim,
    assess_health_report,
    health_catalog,
    project_health_for_extension,
    validate_health_registry,
    validate_health_report,
)


ROOT = Path(__file__).resolve().parents[1]
EVALUATED_AT = "2026-08-11T12:00:00Z"
READY = {
    "configured": True,
    "detected": True,
    "connected": True,
    "authoritative": True,
    "ready": True,
}
EMPTY = {field: False for field in READY}


def _claim(surface_id: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "surface_id": surface_id,
        "lifecycle": dict(READY),
        "observed_at": "2026-08-11T11:59:55Z",
        "last_success": "2026-08-11T11:59:54Z",
        "last_failure": None,
        "degradation": [],
        "blockers": [],
    }
    value.update(changes)
    return value


def _all_claims() -> list[dict[str, object]]:
    catalog = health_catalog(ROOT)
    return [_claim(item["surface_id"]) for item in catalog["surfaces"]]


def test_registry_is_strict_complete_and_extension_projectable() -> None:
    status = validate_health_registry(ROOT)
    assert status == {
        "schema_version": "px.health-registry-validation/1.0",
        "valid": True,
        "surface_count": 7,
        "domains": list(DOMAINS),
        "errors": [],
    }
    catalog = health_catalog(ROOT)
    assert {item["domain"] for item in catalog["surfaces"]} == set(DOMAINS)
    assert all(
        "vscode_extension" in item["projection_consumers"]
        for item in catalog["surfaces"]
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "healthy"),
        ({"degradation": ["events.dropped"]}, "degraded"),
        ({"blockers": ["credentials.missing"]}, "blocked"),
        (
            {
                "observed_at": "2026-08-11T11:50:00Z",
                "last_success": "2026-08-11T11:49:59Z",
            },
            "stale",
        ),
        (
            {
                "lifecycle": EMPTY,
                "observed_at": None,
                "last_success": None,
            },
            "unknown",
        ),
    ],
)
def test_all_five_states_are_derived_from_facts(
    changes: dict[str, object], expected: str
) -> None:
    record = assess_health_claim(
        ROOT,
        _claim("runtime.control-plane", **changes),
        evaluated_at=EVALUATED_AT,
    )
    assert record["state"] == expected
    assert record["freshness"]["stale"] is (expected == "stale")
    assert set(record) == {
        "surface_id",
        "domain",
        "state",
        "lifecycle",
        "authority",
        "freshness",
        "last_success",
        "last_failure",
        "degradation",
        "blockers",
        "remediation",
    }


def test_detected_and_configured_are_independent_but_readiness_is_not() -> None:
    detected_only = dict(EMPTY) | {"detected": True}
    record = assess_health_claim(
        ROOT,
        _claim("sensors.hardware", lifecycle=detected_only, last_success=None),
        evaluated_at=EVALUATED_AT,
    )
    assert record["state"] == "degraded"
    assert record["lifecycle"] == detected_only

    connected_without_detection = dict(EMPTY) | {"connected": True}
    with pytest.raises(HealthModelError, match="requires detected"):
        assess_health_claim(
            ROOT,
            _claim(
                "providers.invocation-gateway", lifecycle=connected_without_detection
            ),
            evaluated_at=EVALUATED_AT,
        )
    false_configuration = dict(READY) | {"configured": False}
    with pytest.raises(HealthModelError, match="every prior"):
        assess_health_claim(
            ROOT,
            _claim("providers.invocation-gateway", lifecycle=false_configuration),
            evaluated_at=EVALUATED_AT,
        )


def test_state_authority_and_time_conflicts_fail_closed() -> None:
    with pytest.raises(HealthModelError, match="claimed state"):
        assess_health_claim(
            ROOT,
            _claim(
                "memory.fabric",
                degradation=["retrieval.degraded"],
                claimed_state="healthy",
            ),
            evaluated_at=EVALUATED_AT,
        )
    with pytest.raises(HealthModelError, match="authority conflicts"):
        assess_health_claim(
            ROOT,
            _claim(
                "memory.fabric",
                authority={
                    "owner": "presentation-layer",
                    "kind": "authoritative",
                    "source": "self assertion",
                },
            ),
            evaluated_at=EVALUATED_AT,
        )
    with pytest.raises(HealthModelError, match="future"):
        assess_health_claim(
            ROOT,
            _claim("memory.fabric", observed_at="2026-08-11T12:00:01Z"),
            evaluated_at=EVALUATED_AT,
        )
    with pytest.raises(HealthModelError, match="newer than observed_at"):
        assess_health_claim(
            ROOT,
            _claim("memory.fabric", last_success="2026-08-11T11:59:56Z"),
            evaluated_at=EVALUATED_AT,
        )


@pytest.mark.parametrize(
    "claim",
    [
        _claim("runtime.control-plane") | {"invented": True},
        _claim("not.registered"),
        _claim("runtime.control-plane", degradation=["same.reason", "same.reason"]),
        _claim("runtime.control-plane", lifecycle=READY, observed_at=None),
        _claim(
            "runtime.control-plane",
            last_failure={"at": "2026-08-11T11:59:54Z", "code": "INVALID CODE"},
        ),
    ],
)
def test_malformed_claims_fail_closed(claim: dict[str, object]) -> None:
    with pytest.raises(HealthModelError):
        assess_health_claim(ROOT, claim, evaluated_at=EVALUATED_AT)


def test_report_is_complete_schema_valid_and_read_only_for_extension() -> None:
    claims = _all_claims()
    claims[1] = claims[1] | {"degradation": ["listener.dropped"]}
    report = assess_health_report(ROOT, claims, evaluated_at=EVALUATED_AT)
    assert report["overall_state"] == "degraded"
    assert report["summary"] == {
        "healthy": 6,
        "degraded": 1,
        "blocked": 0,
        "stale": 0,
        "unknown": 0,
    }
    validate_instance(report, ROOT / "contracts/operations/health-report.schema.json")
    assert validate_health_report(ROOT, report)["valid"] is True
    projection = project_health_for_extension(ROOT, report)
    assert projection["read_only"] is True
    assert projection["source_schema_version"] == "px.health-report/1.0"
    assert projection["records"] == report["records"]
    assert projection["records"] is not report["records"]
    assert (
        projection["records"][0]["authority"] is not report["records"][0]["authority"]
    )


def test_missing_duplicate_and_noncanonical_projection_are_rejected() -> None:
    claims = _all_claims()
    with pytest.raises(HealthModelError, match="coverage mismatch"):
        assess_health_report(ROOT, claims[:-1], evaluated_at=EVALUATED_AT)
    with pytest.raises(HealthModelError, match="duplicate"):
        assess_health_report(ROOT, [*claims, claims[0]], evaluated_at=EVALUATED_AT)
    with pytest.raises(HealthModelError, match="canonical health report"):
        project_health_for_extension(ROOT, {"schema_version": "invented"})


def test_projection_rejects_forged_state_summary_freshness_and_authority() -> None:
    report = assess_health_report(ROOT, _all_claims(), evaluated_at=EVALUATED_AT)
    mutations = []
    forged_state = json.loads(json.dumps(report))
    forged_state["records"][0]["state"] = "blocked"
    mutations.append(forged_state)
    forged_summary = json.loads(json.dumps(report))
    forged_summary["summary"]["healthy"] = 99
    mutations.append(forged_summary)
    forged_age = json.loads(json.dumps(report))
    forged_age["records"][0]["freshness"]["age_seconds"] = 0
    mutations.append(forged_age)
    forged_authority = json.loads(json.dumps(report))
    forged_authority["records"][0]["authority"]["owner"] = "presentation-layer"
    mutations.append(forged_authority)
    for mutation in mutations:
        assert validate_health_report(ROOT, mutation)["valid"] is False
        with pytest.raises(HealthModelError, match="projection rejected"):
            project_health_for_extension(ROOT, mutation)


def test_registry_rejects_duplicate_domains_and_contract_corruption(
    tmp_path: Path,
) -> None:
    (tmp_path / "registry").mkdir()
    (tmp_path / "contracts/operations").mkdir(parents=True)
    shutil.copy2(
        ROOT / "contracts/operations/health-model-registry.schema.json",
        tmp_path / "contracts/operations/health-model-registry.schema.json",
    )
    registry = json.loads((ROOT / "registry/health_taxonomy.json").read_text())
    registry["surfaces"][1]["domain"] = "runtime"
    (tmp_path / "registry/health_taxonomy.json").write_text(json.dumps(registry))
    status = validate_health_registry(tmp_path)
    assert status["valid"] is False
    assert "exactly one surface per domain" in status["errors"][0]

    registry["canonical_owner"] = "presentation-layer"
    (tmp_path / "registry/health_taxonomy.json").write_text(json.dumps(registry))
    status = validate_health_registry(tmp_path)
    assert status["valid"] is False
    assert "invalid canonical health registry" in status["errors"][0]


def test_cli_catalog_and_extension_projection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(ROOT), "health", "catalog"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert catalog["valid"] is True
    claims_path = tmp_path / "claims.json"
    claims_path.write_text(json.dumps({"claims": _all_claims()}))
    assert (
        main(
            [
                "--root",
                str(ROOT),
                "health",
                "assess",
                "--claims",
                str(claims_path),
                "--at",
                EVALUATED_AT,
                "--extension-projection",
            ]
        )
        == 0
    )
    projection = json.loads(capsys.readouterr().out)
    assert projection["schema_version"] == "px.extension-health-input/1.0"
    assert projection["read_only"] is True
