from __future__ import annotations

import json
from pathlib import Path

from runtime.host_boundaries import skill_host_boundary, startup_attribution


def test_startup_attribution_separates_host_owners_and_px(tmp_path: Path) -> None:
    session = tmp_path / "20260816T120000"
    exthost = session / "window1" / "exthost"
    codex = exthost / "openai.chatgpt"
    codex.mkdir(parents=True)
    (session / "main.log").write_text(
        "2026-08-16 11:59:59.800 [info] StorageMainService started\n",
        encoding="utf-8",
    )
    (session / "mcpGateway.log").write_text(
        "2026-08-16 11:59:59.900 [info] [McpGatewayService] Initialized\n",
        encoding="utf-8",
    )
    (exthost / "exthost.log").write_text(
        "\n".join(
            (
                "2026-08-16 12:00:00.000 [info] Extension host with pid 1 started",
                "2026-08-16 12:00:00.100 [info] ExtensionService#_doActivateExtension GitHub.copilot-chat, startup: false",
                "2026-08-16 12:00:00.200 [info] ExtensionService#_doActivateExtension mountain-nomad-bc.pacify-x-vscode, startup: false",
                "2026-08-16 12:00:00.300 [info] ExtensionService#_doActivateExtension ms-python.python, startup: true",
                "2026-08-16 12:00:01.000 [info] Eager extensions activated",
            )
        ),
        encoding="utf-8",
    )
    (codex / "Codex.log").write_text(
        "\n".join(
            (
                "2026-08-16 12:00:00.400 [info] Activating Codex extension",
                "2026-08-16 12:00:00.500 [info] [CodexMcpConnection] Initialize received id=1",
                "2026-08-16 12:00:01.200 [info] [chatgpt-account-lookup] completed result=succeeded",
                "2026-08-16 12:00:01.400 [info] [startup][renderer] app routes mounted after 1000ms",
                "2026-08-16 12:00:01.500 [warning] codex_core_skills::loader: warning",
                "2026-08-16 12:00:01.600 [warning] codex_core_plugins::loader: warning",
                "2026-08-16 12:00:02.000 [info] maybe_resume_success conversationId=redacted-by-parser",
            )
        ),
        encoding="utf-8",
    )

    report = startup_attribution(tmp_path)

    assert report["available"] is True
    assert report["durations_ms"]["extension_host_to_existing_thread_resume"] == 2000
    assert report["vscode_launch"]["launch_to_first_extension_host_ms"] == 200
    assert report["mcp"]["vscode_gateway_initialized"] is True
    assert len(report["cycle_comparison"]) == 1
    assert report["px_attribution"]["activation_request_offset_ms"] == 200
    assert report["px_attribution"]["causal_contribution_to_codex_readiness"] == "not-established-by-host-logs"
    assert {row["owner"] for row in report["milestones"]} >= {
        "vscode-host",
        "codex-host",
        "github-copilot-host",
        "python-extension-host",
        "pacify-x-extension",
    }
    assert "conversationId" not in json.dumps(report)
    assert next(
        row for row in report["milestones"] if row["id"] == "openai.codex.first-usable-tool"
    )["status"] == "host-marker-not-emitted"


def test_skill_host_boundary_reports_global_vendor_gap_without_claiming_control(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    global_root = tmp_path / "global"
    for index in range(10):
        body = root / ".agents" / "skills" / f"px-{index}" / "SKILL.md"
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_text("---\nname: facade\n---\n", encoding="utf-8")
    vendor = global_root / "microsoft-foundry" / "models" / "deploy" / "SKILL.md"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("---\nname: deploy\n---\n", encoding="utf-8")

    report = skill_host_boundary(root, global_skills_root=global_root)

    assert report["project"]["facade_only"] is True
    assert report["microsoft_foundry"]["directly_host_visible"] is True
    assert report["codex_host"]["px_policy_enforced_during_direct_host_selection"] is False
    assert report["remediation"]["required_owner"] == "Codex host or user configuration"
