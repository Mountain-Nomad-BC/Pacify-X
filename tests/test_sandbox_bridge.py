"""The VS Code model bridge exposes a bounded Isolated Agent Sandbox command.

These prove the UI->runtime publish path: the mode is validated, a URL endpoint is
refused, the policy round-trips through the decoder, and no authority is granted.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from runtime.isolated_sandbox import full_component_acknowledgments


def run_bridge(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "runtime.vscode_model_bridge",
         "--engine-root", str(ROOT), "--project-root", ".", "sandbox"],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        cwd=str(ROOT),
    )


@pytest.fixture()
def sandbox_state(tmp_path, monkeypatch):
    # Run the bridge against an isolated project root so no repo state is written.
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("_module_path", project, raising=False)
    yield project


def _run_in(project: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "runtime.vscode_model_bridge",
         "--engine-root", str(ROOT), "--project-root", str(project), "sandbox"],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        cwd=str(ROOT),
    )


def _request(mode: str, **fields: object) -> dict:
    return {
        "schema_version": "px.isolated-agent-sandbox-request/1.0",
        "mode": mode,
        **fields,
    }


def test_bridge_establishes_sandbox_on(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    proc = _run_in(project, _request(
        "ON",
        allowed_endpoints=["api.internal:443"],
        scope_key=project.resolve().as_posix(),
        component_acknowledgments=full_component_acknowledgments(),
    ))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    result = json.loads(proc.stdout.decode("utf-8"))
    assert result["mode"] == "ON"
    assert result["authority_granted"] is False
    assert result["policy"]["network_policy"]["allowed_endpoints"] == ["api.internal:443"]
    assert (project / ".agentic_engineering_os_px/sandbox/isolated-agent-sandbox.json").is_file()


def test_bridge_without_acknowledgments_fails_closed(tmp_path):
    project = tmp_path / "q"
    project.mkdir()
    proc = _run_in(project, _request(
        "ON",
        allowed_endpoints=["api.internal:443"],
        scope_key=project.resolve().as_posix(),
    ))
    assert proc.returncode != 0
    assert b"not ready" in proc.stderr
    assert not (project / ".agentic_engineering_os_px/sandbox/isolated-agent-sandbox.json").is_file()


def test_bridge_sandbox_off(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    proc = _run_in(project, _request("OFF", scope_key=project.resolve().as_posix()))
    assert proc.returncode == 0
    assert json.loads(proc.stdout.decode("utf-8"))["mode"] == "OFF"


def test_bridge_refuses_allowlist_when_sandbox_is_off(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    proc = _run_in(project, _request(
        "OFF",
        allowed_endpoints=["api.internal:443"],
        scope_key=project.resolve().as_posix(),
    ))
    assert proc.returncode != 0
    assert not (project / ".agentic_engineering_os_px/sandbox/isolated-agent-sandbox.json").exists()


def test_bridge_refuses_url_endpoint(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    proc = _run_in(project, _request(
        "ON",
        allowed_endpoints=["https://evil.example/x"],
        scope_key=project.resolve().as_posix(),
    ))
    assert proc.returncode != 0
    assert not (project / ".agentic_engineering_os_px/sandbox/isolated-agent-sandbox.json").exists()


def test_bridge_refuses_unknown_mode(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    proc = _run_in(project, _request("MAYBE", scope_key=project.resolve().as_posix()))
    assert proc.returncode != 0