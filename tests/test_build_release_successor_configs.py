from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import build_release_successor_configs as owner


def test_successor_binds_current_campaign_date_version_and_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(owner, "_git_tag_target", lambda root, tag: "f" * 40)
    automation_base = {
        "candidate_id": "candidate-old",
        "candidate_date": "20260101",
        "predecessor_campaign_id": "candidate-before-old",
        "repair_campaign_id": "repair-old",
        "evidence_prefix": "final-old",
        "artifact": "extension/dist/product-1.0.0.vsix",
        "artifact_sha256": "a" * 64,
        "artifact_size": 10,
        "artifact_mtime_ns": 20,
        "identity_manifest": {"path": "state/final-old-source-manifest.json"},
        "owners": {
            "installed": {
                "command": "audit extension/dist/product-1.0.0.vsix for final-old"
            }
        },
    }
    stage_base = {
        "candidate_id": "candidate-old",
        "predecessor_id": "candidate-before-old",
        "artifact": {
            "path": "extension/dist/product-1.0.0.vsix",
            "sha256": "a" * 64,
            "size": 10,
            "mtime_ns": 20,
            "entry_count": 3,
        },
        "evidence_dir": "evidence/final-old",
        "identity": {
            "path_manifest": "state/final-old-source-manifest.json",
            "commit_message": "Freeze final-old reconciled release state",
            "release_tag": "v1",
            "prior_tag_target": "b" * 40,
        },
        "install": {
            "directory": "installed/product-1.0.0",
            "tree_digest": "c" * 64,
            "version": "1.0.0",
            "entry_count": 2,
        },
    }
    automation_input = tmp_path / "automation.json"
    stage_input = tmp_path / "stage.json"
    automation_output = tmp_path / "successor-automation.json"
    stage_output = tmp_path / "successor-stage.json"
    automation_input.write_text(json.dumps(automation_base), encoding="utf-8")
    stage_input.write_text(json.dumps(stage_base), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "build_release_successor_configs.py",
        "--automation-base", str(automation_input),
        "--stage-base", str(stage_input),
        "--automation-output", str(automation_output),
        "--stage-output", str(stage_output),
        "--old-prefix", "final-old",
        "--new-prefix", "final-new",
        "--candidate-id", "candidate-new",
        "--candidate-date", "20260913",
        "--predecessor-id", "candidate-old",
        "--repair-campaign-id", "repair-current",
        "--artifact", "extension/dist/product-1.0.1.vsix",
        "--artifact-sha256", "d" * 64,
        "--artifact-size", "11",
        "--artifact-mtime-ns", "21",
        "--artifact-entry-count", "4",
        "--installed-directory", "installed/product-1.0.1",
        "--installed-tree-digest", "e" * 64,
        "--installed-version", "1.0.1",
        "--installed-entry-count", "3",
        "--prior-tag-target", "f" * 40,
    ])

    assert owner.main() == 0
    automation = json.loads(automation_output.read_text(encoding="utf-8"))
    stage = json.loads(stage_output.read_text(encoding="utf-8"))
    assert automation["candidate_date"] == "20260913"
    assert automation["timeouts_seconds"]["sections"] > 1800
    assert automation["repair_campaign_id"] == "repair-current"
    assert automation["candidate_id"] == stage["candidate_id"] == "candidate-new"
    assert stage["install"] == {
        "directory": "installed/product-1.0.1",
        "tree_digest": "e" * 64,
        "version": "1.0.1",
        "entry_count": 3,
    }
    combined = automation_output.read_text(encoding="utf-8") + stage_output.read_text(encoding="utf-8")
    for stale in ("20260101", "repair-old", "final-old", "product-1.0.0.vsix"):
        assert stale not in combined
