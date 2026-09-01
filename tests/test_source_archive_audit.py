from __future__ import annotations

from pathlib import Path
import sys

from runtime.resource_lifecycle import ResourceManager
from scripts.audit_source_archive import audit_source_archive


ROOT = Path(__file__).resolve().parents[1]


def test_archive_auditor_routes_through_owned_process_supervisor() -> None:
    source = (ROOT / "scripts" / "audit_source_archive.py").read_text(
        encoding="utf-8"
    )
    assert "subprocess.Popen" not in source
    assert "ProcessSupervisor" in source
    assert "create_workspace" in source
    assert "reclaim_ephemeral_path" in source


def _harness(tmp_path: Path) -> tuple[Path, Path, ResourceManager]:
    root = tmp_path / "project"
    cleanup = tmp_path / "cleanup"
    root.mkdir()
    cleanup.mkdir()
    return root, cleanup, ResourceManager(tmp_path / "state" / "resources.json")


def _archive_builder(*, stderr_bytes: int = 0):
    required = [
        "pyproject.toml",
        "runtime/cli.py",
        "registry/operational_gap_ledger.jsonl",
        ".engineering-bootstrap/project-registry.json",
    ]

    def build(output: Path) -> list[str]:
        code = f"""
import io
import os
from pathlib import Path
import tarfile
if {stderr_bytes}:
    os.write(2, b'x' * {stderr_bytes})
with tarfile.open(Path({str(output)!r}), 'w') as archive:
    for name in {required!r}:
        data = b'x'
        info = tarfile.TarInfo(name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
"""
        return [sys.executable, "-c", code]

    return build


def test_owned_archive_process_succeeds_and_reclaims_workspace(tmp_path: Path) -> None:
    root, cleanup, manager = _harness(tmp_path)
    result = audit_source_archive(
        root,
        resource_manager=manager,
        cleanup_root=cleanup,
        command_builder=_archive_builder(),
        timeout_seconds=10,
    )
    assert result["valid"], result["errors"]
    assert result["process"]["status"] == "exited"
    assert result["process"]["tree_closed"] is True
    assert Path(result["process"]["receipt_path"]).is_file()
    assert result["workspace_cleanup"]["resources_reclaimed"] == 1
    assert not tuple(cleanup.iterdir())


def test_owned_archive_process_times_out_and_reclaims_workspace(tmp_path: Path) -> None:
    root, cleanup, manager = _harness(tmp_path)
    result = audit_source_archive(
        root,
        resource_manager=manager,
        cleanup_root=cleanup,
        command_builder=lambda _output: [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ],
        timeout_seconds=0.2,
    )
    assert result["valid"] is False
    assert result["process"]["status"] in {"startup_timeout", "total_timeout"}
    assert result["process"]["tree_closed"] is True
    assert result["workspace_cleanup"]["resources_reclaimed"] == 1
    assert not tuple(cleanup.iterdir())


def test_stderr_pressure_is_drained_and_bounded(tmp_path: Path) -> None:
    root, cleanup, manager = _harness(tmp_path)
    result = audit_source_archive(
        root,
        resource_manager=manager,
        cleanup_root=cleanup,
        command_builder=_archive_builder(stderr_bytes=200_000),
        timeout_seconds=10,
    )
    assert result["valid"], result["errors"]
    assert result["process"]["stderr_dropped_bytes"] > 0
    assert result["process"]["tree_closed"] is True
    assert result["workspace_cleanup"]["resources_reclaimed"] == 1
