from __future__ import annotations

import json
from pathlib import Path
import zipfile

from scripts.archive_project_map_history import apply, plan


def test_project_map_history_archive_is_verified_and_recoverable(tmp_path: Path) -> None:
    history = tmp_path / ".engineering-bootstrap/project-map-history"
    for index in range(3):
        snapshot = history / f"2026081{index}T000000Z-{index}"
        snapshot.mkdir(parents=True)
        (snapshot / "graph.json").write_text(
            json.dumps({"index": index, "payload": "x" * 1000}), encoding="utf-8"
        )
    dry_run = plan(tmp_path, keep_latest=1)
    assert dry_run["selected_count"] == 2
    assert all(path.is_dir() for path in history.iterdir())
    result = apply(tmp_path, keep_latest=1)
    assert result["changed"] is True
    assert len([path for path in history.iterdir() if path.is_dir()]) == 1
    archive = Path(str(result["archive"]))
    assert archive.is_file()
    with zipfile.ZipFile(archive) as sealed:
        assert sealed.testzip() is None
        assert "MANIFEST.json" in sealed.namelist()
        assert len(sealed.namelist()) == 3
    receipt = json.loads(Path(str(result["receipt"])).read_text(encoding="utf-8"))
    assert receipt["hard_delete_without_archive"] is False
    assert receipt["archive_sha256"] == result["archive_sha256"]
    assert receipt["reclaimed_bytes"] > 0


def test_project_map_history_archive_noops_when_only_retained_set_exists(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / ".engineering-bootstrap/project-map-history/only"
    snapshot.mkdir(parents=True)
    (snapshot / "graph.json").write_text("{}", encoding="utf-8")
    result = apply(tmp_path, keep_latest=1)
    assert result["changed"] is False
    assert snapshot.is_dir()
