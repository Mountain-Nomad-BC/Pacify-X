from __future__ import annotations

from scripts.build_operation_health_snapshot import (
    INSTALLED_LISTENER_RECEIPT,
    _extension_health_claim,
    _receipt_health,
)


def test_current_platform_listener_receipt_is_retained() -> None:
    from pathlib import Path

    assert Path(INSTALLED_LISTENER_RECEIPT).is_file()


def test_listener_receipt_presence_does_not_fabricate_healthy_coverage() -> None:
    health, limitation = _receipt_health(
        "extension.vscode-listener",
        {"listener_health": {"status": "partial", "coverage_complete": False}},
    )
    assert health == "unknown"
    assert "incomplete" in str(limitation)


def test_listener_receipt_requires_healthy_complete_claim() -> None:
    health, limitation = _receipt_health(
        "extension.vscode-listener",
        {"listener_health": {"status": "healthy", "coverage_complete": True}},
    )
    assert health == "healthy"
    assert limitation is None


def test_installed_receipt_reads_listener_claim_from_host_envelope() -> None:
    health, limitation = _receipt_health(
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
