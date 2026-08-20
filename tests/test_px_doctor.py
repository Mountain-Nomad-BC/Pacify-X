from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from runtime.px_doctor import (
    SCHEMA_VERSION,
    _environment_handoff_probe,
    compose_doctor_report,
    render_doctor_human,
    retain_doctor_receipt,
    run_px_doctor,
)
from runtime.wal_transaction import JsonWal


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
EVALUATED_AT = "2026-08-11T18:00:00.000Z"
WAL_ROOTS = (
    ".engineering-bootstrap/operations/wal",
    ".engineering-bootstrap/provider-budget/wal",
    ".engineering-bootstrap/resource-lifecycle/wal",
    ".engineering-bootstrap/coordination/wal",
    ".engineering-bootstrap/diagnostics/wal",
)


def _sections(name: str) -> dict[str, dict[str, object]]:
    states = json.loads((FIXTURES / f"px_doctor_{name}.json").read_text())
    return {
        section: {
            "state": state,
            "summary": f"{section} is {state}",
            "details": {"fixture": name},
            "remediation": {
                "summary": f"repair {section}",
                "deep_link": f"px://doctor/{section}",
            },
        }
        for section, state in states.items()
    }


def _wal_snapshot(root: Path) -> list[tuple[object, ...]]:
    records: list[tuple[object, ...]] = []
    for relative_root in WAL_ROOTS:
        wal_root = root / relative_root
        records.append((relative_root, "root_exists", wal_root.exists()))
        if not wal_root.exists():
            continue
        for path in sorted(wal_root.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(root).as_posix()
            stat = path.lstat()
            if path.is_dir():
                records.append((relative, "directory", stat.st_mtime_ns))
            else:
                payload = path.read_bytes()
                records.append(
                    (
                        relative,
                        "file",
                        len(payload),
                        stat.st_mtime_ns,
                        hashlib.sha256(payload).hexdigest(),
                    )
                )
    return records


@pytest.mark.parametrize(
    ("fixture", "state", "operable", "ready"),
    (
        ("healthy", "healthy", True, True),
        ("degraded", "degraded", True, False),
        ("blocked", "blocked", False, False),
    ),
)
def test_fixture_states_are_composed_without_strengthening(
    fixture: str, state: str, operable: bool, ready: bool
) -> None:
    report = compose_doctor_report(_sections(fixture), evaluated_at=EVALUATED_AT)
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["overall_state"] == state
    assert report["valid"] is True
    assert report["operable"] is operable
    assert report["ready"] is ready
    assert report["certification_ready"] is ready
    unsigned = dict(report)
    digest = unsigned.pop("report_sha256")
    encoded = (
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        + b"\n"
    )
    assert digest == hashlib.sha256(encoded).hexdigest()


def test_human_projection_contains_every_section_and_deep_link() -> None:
    report = compose_doctor_report(_sections("degraded"), evaluated_at=EVALUATED_AT)
    rendered = render_doctor_human(report)
    assert rendered.startswith("PX Doctor: DEGRADED")
    for section in _sections("degraded"):
        assert section.replace("_", " ") in rendered
        assert f"px://doctor/{section}" in rendered


def test_receipt_is_hash_bound_and_wal_recoverable(tmp_path: Path) -> None:
    report = compose_doctor_report(_sections("blocked"), evaluated_at=EVALUATED_AT)
    retained = retain_doctor_receipt(tmp_path, report, Path("diagnostics"))
    receipt = json.loads((tmp_path / retained["path"]).read_text())
    assert receipt["report_sha256"] == report["report_sha256"]
    assert receipt["report"] == report
    assert (
        hashlib.sha256((tmp_path / retained["path"]).read_bytes()).hexdigest()
        == retained["sha256"]
    )
    assert (
        JsonWal(tmp_path / "diagnostics" / "wal", tmp_path).recover()["valid"] is True
    )


def test_receipt_refuses_root_or_external_destination(tmp_path: Path) -> None:
    report = compose_doctor_report(_sections("healthy"), evaluated_at=EVALUATED_AT)
    with pytest.raises(ValueError, match="below the project root"):
        retain_doctor_receipt(tmp_path, report, tmp_path)
    with pytest.raises(ValueError, match="below the project root"):
        retain_doctor_receipt(tmp_path, report, tmp_path.parent / "elsewhere")


def test_live_doctor_covers_full_stack_without_writing() -> None:
    before = _wal_snapshot(ROOT)
    report = run_px_doctor(ROOT, evaluated_at=EVALUATED_AT)
    after = _wal_snapshot(ROOT)
    assert set(report["sections"]) == set(_sections("healthy"))
    assert report["sections"]["coverage"]["details"]["route_count"] >= 1
    assert "recovery" in report["sections"]["transactions_wal"]["details"]
    assert report["sections"]["providers_budgets"]["details"]["default_deny"] is True
    git_details = report["sections"]["git"]["details"]
    if (ROOT / ".git").exists():
        assert git_details["untracked_files_examined"] is True
        assert git_details["untracked_file_count"] >= 1
        assert git_details["untracked_count_truncated"] is False
    else:
        assert git_details["repository"] is False
    assert (
        report["sections"]["environment_handoff"]["details"]["secret_values_retained"]
        is False
    )
    assert report["sections"]["extension"]["details"]["health_claim_present"] is False
    assert before == after


def test_environment_handoff_probe_marks_old_evidence_stale(tmp_path: Path) -> None:
    environment = tmp_path / ".engineering-bootstrap/environment/current.json"
    handoff = tmp_path / ".engineering-bootstrap/coordination/handoff.json"
    environment.parent.mkdir(parents=True)
    handoff.parent.mkdir(parents=True)
    environment.write_text(json.dumps({
        "schema_version": "px.environment-capability-map/1.0",
        "snapshot_hash": "a" * 64,
        "generated_utc": "2026-08-10T00:00:00Z",
    }), encoding="utf-8")
    handoff.write_text(json.dumps({
        "schema_version": "px.coordination-handoff/1.0",
        "verified_state_hash": "b" * 64,
        "generated_utc": "2026-08-10T00:00:00Z",
    }), encoding="utf-8")
    result = _environment_handoff_probe(
        tmp_path, evaluated_at="2026-08-14T00:00:00Z"
    )
    assert result["state"] == "degraded"
    assert result["details"]["environment_fresh"] is False
    assert result["details"]["handoff_fresh"] is False
    assert "environment_stale" in result["details"]["problems"]


def test_environment_handoff_age_is_not_stale_when_state_hash_is_current(
    tmp_path: Path,
) -> None:
    environment = tmp_path / ".engineering-bootstrap/environment/current.json"
    handoff = tmp_path / ".engineering-bootstrap/coordination/handoff.json"
    state = tmp_path / ".engineering-bootstrap/coordination/state.json"
    environment.parent.mkdir(parents=True)
    handoff.parent.mkdir(parents=True)
    environment.write_text(json.dumps({
        "schema_version": "px.environment-capability-map/2.0",
        "snapshot_hash": "a" * 64,
        "generated_utc": "2026-08-10T00:00:00Z",
    }), encoding="utf-8")
    state.write_text(json.dumps({"state_hash": "b" * 64}), encoding="utf-8")
    handoff.write_text(json.dumps({
        "schema_version": "px.coordination-handoff/1.0",
        "verified_state_hash": "b" * 64,
        "generated_utc": "2026-08-10T00:00:00Z",
    }), encoding="utf-8")
    result = _environment_handoff_probe(
        tmp_path, evaluated_at="2026-08-14T00:00:00Z"
    )
    assert result["details"]["handoff_fresh"] is True
    assert result["details"]["handoff_state_current"] is True
    assert "handoff_stale" not in result["details"]["problems"]
    assert result["details"]["environment_fresh"] is False


def test_composer_rejects_missing_sections_and_bad_links() -> None:
    sections = _sections("healthy")
    sections.pop("git")
    with pytest.raises(ValueError, match="section mismatch"):
        compose_doctor_report(sections, evaluated_at=EVALUATED_AT)
    sections = _sections("healthy")
    sections["git"]["remediation"]["deep_link"] = "https://not-canonical.invalid"
    with pytest.raises(ValueError, match="deep link"):
        compose_doctor_report(sections, evaluated_at=EVALUATED_AT)
