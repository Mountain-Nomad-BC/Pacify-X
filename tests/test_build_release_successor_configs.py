from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts import build_release_successor_configs as owner


def _make_vsix(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("extension.vsixmanifest", "<PackageManifest />")
        archive.writestr(
            "extension/package.json",
            json.dumps({"name": "product", "version": "1.0.1"}),
        )
        archive.writestr("extension/extension.js", "module.exports = {};\n")


def test_successor_binds_current_campaign_date_version_and_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    artifact = root / "extension" / "dist" / "product-1.0.1.vsix"
    _make_vsix(artifact)

    installed = root / "installed" / "product-1.0.1"
    installed.mkdir(parents=True)
    (installed / "package.json").write_text(
        json.dumps({"name": "product", "version": "1.0.1"}),
        encoding="utf-8",
    )
    (installed / "extension.js").write_text(
        "module.exports = {};\n",
        encoding="utf-8",
    )
    (installed / ".vsixmanifest").write_text(
        "<PackageManifest />",
        encoding="utf-8",
    )

    code_command = root / "code.cmd"
    code_command.write_text("@echo off\n", encoding="utf-8")

    cohesion_dag = root / "cohesion-dag.json"
    cohesion_dag.write_text("{}\n", encoding="utf-8")

    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()

    artifact_dir = root / "release-artifacts"
    artifact_dir.mkdir()

    signing_key = root / "signing.key"
    signing_key.write_text("test-key\n", encoding="utf-8")

    spec = {
        "schema_version": owner.SPEC_SCHEMA,
        "root": str(root),
        "candidate_id": "candidate-20260919-new",
        "candidate_date": "20260919",
        "predecessor_campaign_id": "candidate-old",
        "repair_campaign_id": "repair-current",
        "evidence_prefix": "final-new",
        "release_version": "1.0.1",
        "artifact": "extension/dist/product-1.0.1.vsix",
        "install": {
            "directory": str(installed),
            "code_command": str(code_command),
        },
        "cohesion_dag": str(cohesion_dag),
        "finalize": {
            "wheelhouse": str(wheelhouse),
            "artifact_dir": str(artifact_dir),
            "signing_key": str(signing_key),
        },
    }

    spec_path = root / "spec.json"
    automation_output = root / "state" / "successor-automation.json"
    stage_output = root / "state" / "successor-stage.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    monkeypatch.setattr(
        owner,
        "_validate_frozen_source",
        lambda candidate_root: ("a" * 40, "origin/main", "a" * 40),
    )
    monkeypatch.setattr(
        owner,
        "_release_version",
        lambda candidate_root, expected: "1.0.1",
    )
    monkeypatch.setattr(
        owner,
        "_git",
        lambda candidate_root, *args: (
            "f" * 40
            if args == ("rev-list", "-n", "1", "v1.0.1")
            else (_ for _ in ()).throw(
                AssertionError(f"unexpected git call: {args!r}")
            )
        ),
    )
    monkeypatch.setattr(
        owner,
        "_timeout_map",
        lambda candidate_root, overrides: {
            step: owner.DEFAULT_TIMEOUTS[step]
            for step in owner.STEP_ORDER
        },
    )

    result = owner.build(
        spec_path,
        automation_output,
        stage_output,
    )

    assert result["valid"] is True

    automation = json.loads(
        automation_output.read_text(encoding="utf-8")
    )
    stage = json.loads(
        stage_output.read_text(encoding="utf-8")
    )

    assert automation["candidate_date"] == "20260919"
    assert automation["repair_campaign_id"] == "repair-current"
    assert automation["candidate_id"] == stage["candidate_id"] == (
        "candidate-20260919-new"
    )
    assert automation["predecessor_campaign_id"] == "candidate-old"

    assert stage["artifact"]["path"] == (
        "extension/dist/product-1.0.1.vsix"
    )
    assert stage["install"]["directory"] == str(installed.resolve())
    assert stage["install"]["version"] == "1.0.1"

    combined = (
        automation_output.read_text(encoding="utf-8")
        + stage_output.read_text(encoding="utf-8")
    )
    for stale in (
        "final-old",
        "product-1.0.0.vsix",
        "repair-old",
    ):
        assert stale not in combined