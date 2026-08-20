from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.reconcile_punch_card_evidence import reconcile


def test_reconciler_refreshes_hash_without_promoting_open_record(tmp_path: Path) -> None:
    artifact = tmp_path / "runtime/owner.py"
    artifact.parent.mkdir()
    artifact.write_text("# current\n", encoding="utf-8")
    evidence = tmp_path / "evidence/punch-cards"
    evidence.mkdir(parents=True)
    accepted = {
        "schema_version": "px.punch-card-evidence/1.0",
        "card_id": "O01",
        "status": "accepted",
        "artifacts": [{"path": "runtime/owner.py", "sha256": "0" * 64}],
    }
    open_record = {**accepted, "card_id": "O02", "status": "open"}
    (evidence / "O01.json").write_text(json.dumps(accepted), encoding="utf-8")
    (evidence / "O02.json").write_text(json.dumps(open_record), encoding="utf-8")

    assert not reconcile(tmp_path)["valid"]
    assert reconcile(tmp_path, apply=True)["valid"]
    updated = json.loads((evidence / "O01.json").read_text(encoding="utf-8"))
    untouched = json.loads((evidence / "O02.json").read_text(encoding="utf-8"))
    assert updated["artifacts"][0]["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert untouched["artifacts"][0]["sha256"] == "0" * 64


def test_reconciler_refuses_missing_or_escaping_artifacts(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence/punch-cards"
    evidence.mkdir(parents=True)
    record = {
        "schema_version": "px.punch-card-evidence/1.0",
        "card_id": "O01",
        "status": "accepted",
        "artifacts": [{"path": "../outside", "sha256": "0" * 64}],
    }
    (evidence / "O01.json").write_text(json.dumps(record), encoding="utf-8")
    report = reconcile(tmp_path, apply=True)
    assert not report["valid"]
    assert "escapes root" in report["errors"][0]
