from __future__ import annotations

from pathlib import Path

import pytest

from scripts.build_operation_health_snapshot import (
    INSTALLED_LISTENER_RECEIPT,
    _extension_health_claim,
    _receipt_observed_at,
    _receipt_health,
)


ROOT = Path(__file__).resolve().parents[1]


def test_current_platform_listener_receipt_is_retained() -> None:
    receipt = ROOT / INSTALLED_LISTENER_RECEIPT
    if not receipt.is_file():
        pytest.skip("current installed-host evidence is intentionally outside source control")
    assert receipt.stat().st_size > 0


def test_listener_receipt_presence_does_not_fabricate_healthy_coverage() -> None:
    health, limitation = _receipt_health(
        ROOT,
        "extension.vscode-listener",
        {"listener_health": {"status": "partial", "coverage_complete": False}},
    )
    assert health == "unknown"
    assert "incomplete" in str(limitation)


def test_listener_receipt_requires_healthy_complete_claim() -> None:
    health, limitation = _receipt_health(
        ROOT,
        "extension.vscode-listener",
        {"listener_health": {"status": "healthy", "coverage_complete": True}},
    )
    assert health == "healthy"
    assert limitation is None


def test_installed_receipt_reads_listener_claim_from_host_envelope() -> None:
    health, limitation = _receipt_health(
        ROOT,
        "extension.vscode-listener",
        {
            "schema_version": "px.installed-vsix-certification/1.0",
            "host": {
                "listener_health": {
                    "status": "healthy",
                    "coverage_complete": True,
                }
            },
        },
    )
    assert health == "healthy"
    assert limitation is None


def test_remote_provider_is_not_reported_healthy_from_static_acceptance_evidence() -> None:
    health, limitation = _receipt_health(
        ROOT,
        "provider.remote-model",
        {"adapters": [{"provider_id": "openai", "admitted": False, "status": "unconfigured"}]},
    )
    assert health == "unconfigured"
    assert "default-off" in str(limitation)


def test_canonical_environment_requires_secret_safe_current_inventory() -> None:
    health, limitation = _receipt_health(
        ROOT,
        "runtime.package-environment",
        {
            "schema_version": "px.environment-capability-map/2.0",
            "snapshot_hash": "a" * 64,
            "boundaries": {"credential_values_persisted": False},
        },
    )
    assert health == "healthy"
    assert limitation is None


def test_installed_receipt_projects_canonical_extension_health_facts() -> None:
    claim = _extension_health_claim(
        {
            "artifact": {"name": "px.vsix", "unchanged": True},
            "engine_connected": True,
            "process_lifecycle": {
                "finished_utc": "2026-08-15T02:17:47Z",
                "process_tree_closed_verified": True,
            },
            "host": {
                "vscode_version": "1.132.1",
                "listener_health": {
                    "status": "healthy",
                    "coverage_complete": True,
                    "canonical_bus_connected": True,
                    "dropped_events": 0,
                },
            },
        }
    )
    assert claim["surface_id"] == "extension.activity-projection"
    assert all(claim["lifecycle"].values())
    assert claim["degradation"] == []
    assert claim["blockers"] == []


def test_health_snapshot_preserves_installed_host_observation_time(tmp_path: Path) -> None:
    receipt = tmp_path / "installed.json"
    receipt.write_text("{}\n", encoding="utf-8")
    observed = _receipt_observed_at(
        receipt,
        "extension.vscode-listener",
        {"process_lifecycle": {"finished_utc": "2026-08-15T02:17:47Z"}},
    )
    assert observed == "2026-08-15T02:17:47+00:00"


def test_health_snapshot_uses_environment_generation_time(tmp_path: Path) -> None:
    receipt = tmp_path / "environment.json"
    receipt.write_text("{}\n", encoding="utf-8")
    observed = _receipt_observed_at(
        receipt,
        "runtime.package-environment",
        {"generated_utc": "2026-08-26T13:41:31.562Z"},
    )
    assert observed == "2026-08-26T13:41:31.562000+00:00"
