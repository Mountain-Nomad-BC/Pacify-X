from __future__ import annotations

import json
from pathlib import Path
import zipfile

from scripts.archive_committed_wal import apply, plan


def test_committed_wal_archive_keeps_recent_transactions_recoverable(
    tmp_path: Path,
) -> None:
    committed = tmp_path / ".engineering-bootstrap/operation-bus/wal/committed"
    for index in range(4):
        transaction = committed / f"operation-{index:08d}-test"
        transaction.mkdir(parents=True)
        (transaction / "manifest.json").write_text(
            json.dumps({"index": index, "payload": "x" * 1000}), encoding="utf-8"
        )
    dry_run = plan(tmp_path, keep_latest=2)
    assert dry_run["selected_count"] == 2
    result = apply(tmp_path, keep_latest=2)
    assert result["changed"] is True
    assert len([path for path in committed.iterdir() if path.is_dir()]) == 2
    archive = Path(str(result["archive"]))
    with zipfile.ZipFile(archive) as sealed:
        assert sealed.testzip() is None
        assert len(sealed.namelist()) == 3
    receipt = json.loads(Path(str(result["receipt"])).read_text(encoding="utf-8"))
    assert receipt["hard_delete_without_archive"] is False
    assert receipt["archive_sha256"] == result["archive_sha256"]
