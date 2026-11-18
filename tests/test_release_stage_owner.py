from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from scripts.run_release_stage_owner import (
    Config,
    OwnerBlocked,
    ProductionEffects,
    STEPS,
    check,
    main,
    plan,
    run,
    resource_postcondition,
    required_section_evidence,
)


def test_vscode_cli_resolves_wrapper_selected_version_not_arbitrary_directory(tmp_path):
    from scripts.run_release_stage_owner import vscode_cli_entrypoint
    executable = tmp_path / "Code.exe"
    executable.write_bytes(b"fixture")
    (tmp_path / "bin").mkdir()
    wrapper = tmp_path / "bin/code.cmd"
    wrapper.write_text('@echo off\n"%~dp0..\\Code.exe" "%~dp0..\\a717861c07\\resources\\app\\out\\cli.js" %*\n')
    for version in ("a717861c07", "69047191fc"):
        cli = tmp_path / version / "resources/app/out/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("fixture")
    selected = tmp_path / "a717861c07/resources/app/out/cli.js"
    assert vscode_cli_entrypoint(executable) == selected
    import os
    if os.name == "nt":
        from dataclasses import replace
        from runtime.release_process_custody import assert_release_command_argv, release_command_effects
        from scripts.run_release_stage_owner import vscode_cli_argv
        from runtime.release_source_identity import release_private_installation_relative
        (tmp_path / "project").mkdir()
        config = replace(fixture(tmp_path / "project", "install"), code_command=executable)
        private = config.root / release_private_installation_relative(config.candidate_id)
        argv = vscode_cli_argv(config, "--user-data-dir", str(private / "user-data"),
            "--extensions-dir", str(private / "extensions"), "--list-extensions", "--show-versions")
        assert_release_command_argv(config, "install-list", argv)
        targets, _ = release_command_effects(config, "install-list", argv)
        assert ("read", str(selected)) in targets
    wrapper.write_text(wrapper.read_text().replace("a717861c07", "0000000000"))
    with pytest.raises(OwnerBlocked, match="unavailable"):
        vscode_cli_entrypoint(executable)


@pytest.mark.parametrize("target", ["../escape", "..\\escape", "A717861C07", "a717861c07&whoami"])
def test_vscode_cli_rejects_unbounded_wrapper_targets(tmp_path, target):
    from scripts.run_release_stage_owner import vscode_cli_entrypoint
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/code.cmd").write_text(
        f'"%~dp0..\\Code.exe" "%~dp0..\\{target}\\resources\\app\\out\\cli.js" %*\n')
    with pytest.raises(OwnerBlocked, match="exactly one"):
        vscode_cli_entrypoint(tmp_path / "Code.exe")


def test_vscode_cli_rejects_ambiguous_wrapper(tmp_path):
    from scripts.run_release_stage_owner import vscode_cli_entrypoint
    (tmp_path / "bin").mkdir()
    line = '"%~dp0..\\Code.exe" "%~dp0..\\a717861c07\\resources\\app\\out\\cli.js" %*\n'
    (tmp_path / "bin/code.cmd").write_text(line * 2)
    with pytest.raises(OwnerBlocked, match="exactly one"):
        vscode_cli_entrypoint(tmp_path / "Code.exe")


def test_required_section_receipt_uses_the_actual_denominator_and_hashes():
    names = [f'section-{i}' for i in range(8)]
    status = {'valid': True, 'required_sections': names,
              'sections': [{'section': name, 'current': True, 'input_sha256': 'a' * 64} for name in names]}
    evidence = required_section_evidence(status)
    assert evidence['required_section_count'] == 8
    assert len(evidence['required_section_inputs']) == 8
    status['sections'].pop()
    with pytest.raises(OwnerBlocked, match='unique current'):
        required_section_evidence(status)


class FakeEffects:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.verified: list[str] = []

    def execute(self, step: str, config: Config) -> dict[str, object]:
        self.executed.append(step)
        return {"valid": True}

    def verify(self, step: str, config: Config) -> None:
        self.verified.append(step)


def test_release_owners_read_current_revision_campaign(tmp_path, monkeypatch):
    from scripts import run_release_candidate, run_release_stage_owner
    config = fixture(tmp_path, "package")
    current = tmp_path / "revision" / "repair-campaign.json"
    current.parent.mkdir()
    expected = {"campaign_id": "current", "phase": "validated", "intake_open": False, "unresolved": []}
    current.write_text(json.dumps(expected), encoding="utf-8")
    monkeypatch.setattr("runtime.project_revision_succession.current_campaign_path", lambda root: current)
    assert run_release_stage_owner.repair(config) == expected
    assert run_release_candidate._repair(config) == expected


def test_stage_owner_advances_current_revision_without_touching_legacy(tmp_path, monkeypatch):
    config = fixture(tmp_path, "package")
    legacy = tmp_path / ".agentic_engineering_os_px/processing-order/repair-campaign.json"
    before = legacy.read_bytes()
    current = tmp_path / "revision" / "repair-campaign.json"
    current.parent.mkdir()
    current.write_text(json.dumps({"phase": "validated", "intake_open": False, "unresolved": []}), encoding="utf-8")
    monkeypatch.setattr("runtime.project_revision_succession.current_campaign_path", lambda root: current)
    ProductionEffects().advance(config, "validated", "packaged")
    assert json.loads(current.read_text())["phase"] == "packaged"
    assert legacy.read_bytes() == before


def test_release_owners_do_not_fall_back_from_missing_current_campaign(tmp_path, monkeypatch):
    from scripts import run_release_candidate, run_release_stage_owner
    config = fixture(tmp_path, "package")
    current = tmp_path / "missing-current.json"
    monkeypatch.setattr("runtime.project_revision_succession.current_campaign_path", lambda root: current)
    for reader in (run_release_stage_owner.repair, run_release_candidate._repair):
        with pytest.raises(OSError):
            reader(config)
    with pytest.raises(OSError):
        ProductionEffects().advance(config, "validated", "packaged")


def fixture(tmp_path: Path, step: str) -> Config:
    artifact = tmp_path / "candidate.vsix"
    artifact.write_bytes(b"artifact")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "px.release-identity-path-manifest/1.0",
                "candidate_id": "pacify-x-certification-20260905-final100-single",
                "paths": [],
                "mutable_paths": ["manifest.json"],
            }
        ),
        encoding="utf-8",
    )
    state_dir = tmp_path / ".agentic_engineering_os_px/processing-order"
    state_dir.mkdir(parents=True)
    before = {
        "archive_clear": "repair_frozen",
        "reconcile": "repair_frozen",
        "identity": "revision_reconciled",
        "sections": "revision_reconciled",
        "full_profile": "sections_current",
        "validate": "full_profile_passed",
        "package": "validated",
        "install": "packaged",
    }[step]
    (state_dir / "repair-campaign.json").write_text(
        json.dumps(
            {
                "campaign_id": "pacify-x-cohesion-closure-repair12-20260905",
                "phase": before,
                "intake_open": False,
                "unresolved": [],
            }
        ),
        encoding="utf-8",
    )
    candidate = "pacify-x-certification-20260905-final100-single"
    predecessor = "pacify-x-certification-20260905-final99-single"
    if step == "archive_clear":
        release = {"campaign_id": predecessor, "state": "failed", "active_claim": None}
    elif step in {"reconcile", "identity"}:
        release = {
            "campaign_id": candidate,
            "state": "cleared",
            "apply_count": 0,
            "identity": None,
            "active_claim": None,
        }
    else:
        index = STEPS[3:].index(step)
        stages = {
            name: {
                "status": "passed" if position < index else "pending",
                "claim_id": None,
            }
            for position, name in enumerate(
                (
                    "sections",
                    "full_profile",
                    "validate",
                    "package",
                    "install",
                    "installed_operational",
                    "certify",
                )
            )
        }
        release = {
            "campaign_id": candidate,
            "state": "active",
            "apply_count": 1,
            "identity": {"release_identity_sha256": "a" * 64},
            "active_claim": None,
            "stages": stages,
        }
    release["repair_campaign_id"] = "pacify-x-cohesion-closure-repair12-20260905"
    (state_dir / "release-identity.json").write_text(
        json.dumps(release), encoding="utf-8"
    )
    info = artifact.stat()
    return Config(
        root=tmp_path,
        candidate_id=candidate,
        predecessor_id=predecessor,
        artifact=artifact,
        artifact_sha256=hashlib.sha256(b"artifact").hexdigest(),
        artifact_size=info.st_size,
        artifact_mtime_ns=info.st_mtime_ns,
        evidence_dir=tmp_path / "evidence",
        log_dir=tmp_path / "logs",
        path_manifest=manifest,
        commit_message="Freeze final100",
        release_tag="v0.7.0",
        prior_tag_target="0" * 40,
        zip_entry_count=1,
        installed_dir=tmp_path / "installed",
        code_command=tmp_path / "code.cmd",
        installed_tree_digest="b" * 64,
        installed_version="0.6.85",
        installable_entry_count=1,
    )


@pytest.mark.parametrize("step", STEPS)
def test_each_invocation_admits_only_selected_step(
    tmp_path: Path, step: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, step)
    if step == "identity":
        monkeypatch.setattr(
            "runtime.release_identity._release_dirty_state",
            lambda root: {
                "blocking_paths": [],
                "mutable_control_paths": [],
                "classifier_errors": [],
            },
        )
    effects = FakeEffects()
    result = run(config, step, effects)
    assert result["step"] == step
    assert result["one_step"] is True
    assert effects.executed == [step]
    assert effects.verified == [step]


def test_plan_is_effect_free_and_check_rejects_wrong_phase(tmp_path: Path) -> None:
    config = fixture(tmp_path, "package")
    before = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
    )
    assert plan(config, "package")["effects"] is False
    after = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
    )
    assert after == before
    repair = tmp_path / ".agentic_engineering_os_px/processing-order/repair-campaign.json"
    value = json.loads(repair.read_text(encoding="utf-8"))
    value["phase"] = "installed"
    repair.write_text(json.dumps(value), encoding="utf-8")
    assert check(config, "package")["valid"] is False


def test_identity_check_rejects_missing_manifest_before_execution(tmp_path: Path) -> None:
    config = fixture(tmp_path, "identity")
    config.path_manifest.unlink()

    result = check(config, "identity")

    assert result["valid"] is False
    assert any("identity manifest is not ready" in error for error in result["errors"])


def test_identity_check_rejects_wrong_candidate_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, "identity")
    manifest = json.loads(config.path_manifest.read_text(encoding="utf-8"))
    manifest["candidate_id"] = "another-candidate"
    config.path_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        "runtime.release_identity._release_dirty_state",
        lambda root: {
            "blocking_paths": ["one.txt", "two.txt"],
            "mutable_control_paths": [],
            "classifier_errors": [],
        },
    )

    assert check(config, "identity")["valid"] is False


def test_archive_check_allows_one_unused_cleared_predecessor(tmp_path: Path) -> None:
    config = fixture(tmp_path, "archive_clear")
    state = tmp_path / ".agentic_engineering_os_px/processing-order/release-identity.json"
    state.write_text(
        json.dumps(
            {
                "schema_version": "px.release-campaign/1.0",
                "campaign_id": config.predecessor_id,
                "repair_campaign_id": "pacify-x-cohesion-closure-repair12-20260905",
                "state": "cleared",
                "apply_count": 0,
                "identity": None,
                "active_claim": None,
                "stages": {
                    name: {"status": "pending", "claim_id": None}
                    for name in (
                        "sections",
                        "full_profile",
                        "validate",
                        "package",
                        "install",
                        "installed_operational",
                        "certify",
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    assert check(config, "archive_clear")["valid"] is True
    repair = tmp_path / ".agentic_engineering_os_px/processing-order/repair-campaign.json"
    repair_value = json.loads(repair.read_text(encoding="utf-8"))
    repair_value["phase"] = "revision_reconciled"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    assert check(config, "archive_clear")["valid"] is True


def test_owner_binds_non_archive_steps_to_current_repair_campaign(
    tmp_path: Path,
) -> None:
    config = fixture(tmp_path, "reconcile")
    state_dir = tmp_path / ".agentic_engineering_os_px/processing-order"
    repair_path = state_dir / "repair-campaign.json"
    release_path = state_dir / "release-identity.json"
    repair = json.loads(repair_path.read_text(encoding="utf-8"))
    release = json.loads(release_path.read_text(encoding="utf-8"))
    repair["campaign_id"] = "current-repair-campaign"
    release["repair_campaign_id"] = "current-repair-campaign"
    repair_path.write_text(json.dumps(repair), encoding="utf-8")
    release_path.write_text(json.dumps(release), encoding="utf-8")
    assert check(config, "reconcile")["valid"] is True
    release["repair_campaign_id"] = "obsolete-repair-campaign"
    release_path.write_text(json.dumps(release), encoding="utf-8")
    assert check(config, "reconcile")["valid"] is False


def test_archive_check_rejects_unmarked_chained_preidentity_predecessor(
    tmp_path: Path,
) -> None:
    config = fixture(tmp_path, "archive_clear")
    state = tmp_path / ".agentic_engineering_os_px/processing-order/release-identity.json"
    value = json.loads(state.read_text(encoding="utf-8"))
    value.update(
        schema_version="px.release-campaign/1.0",
        repair_campaign_id="pacify-x-cohesion-closure-repair12-20260905",
        state="cleared",
        apply_count=0,
        identity=None,
        pre_identity_reconciliation_successor=True,
        stages={
            name: {"status": "pending", "claim_id": None}
            for name in (
                "sections",
                "full_profile",
                "validate",
                "package",
                "install",
                "installed_operational",
                "certify",
            )
        },
    )
    state.write_text(json.dumps(value), encoding="utf-8")

    assert check(config, "archive_clear")["valid"] is False

    value["pre_identity_failure"] = {
        "schema_version": "px.pre-identity-owner-failure/1.0",
        "campaign_id": config.predecessor_id,
        "owner": "reconcile",
        "status": "failed",
        "attempt_count": 1,
        "error": "ValueError: failed classification",
        "recorded_at": "2026-09-06T00:00:00Z",
    }
    state.write_text(json.dumps(value), encoding="utf-8")
    assert check(config, "archive_clear")["valid"] is True


@pytest.mark.parametrize("step", ["reconcile", "identity"])
def test_execute_failure_marks_exact_current_preidentity_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    config = fixture(tmp_path, step)
    state = tmp_path / ".agentic_engineering_os_px/processing-order/release-identity.json"
    value = json.loads(state.read_text(encoding="utf-8"))
    value.update(
        schema_version="px.release-campaign/1.0",
        repair_campaign_id="pacify-x-cohesion-closure-repair12-20260905",
        stages={
            name: {"status": "pending", "claim_id": None}
            for name in (
                "sections",
                "full_profile",
                "validate",
                "package",
                "install",
                "installed_operational",
                "certify",
            )
        },
    )
    state.write_text(json.dumps(value), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.run_release_stage_owner.Config.load", lambda _path: config
    )
    monkeypatch.setattr(
        "scripts.run_release_stage_owner.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OwnerBlocked("classification failed")
        ),
    )

    assert main(["--config", str(config_path), "--step", step, "--execute"]) == 1
    marked = json.loads(state.read_text(encoding="utf-8"))["pre_identity_failure"]
    assert marked["campaign_id"] == config.candidate_id
    assert marked["owner"] == step
    assert marked["attempt_count"] == 1


def test_archive_check_allows_one_unused_invalid_identity_predecessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, "archive_clear")
    repair = tmp_path / ".agentic_engineering_os_px/processing-order/repair-campaign.json"
    repair_value = json.loads(repair.read_text(encoding="utf-8"))
    repair_value["phase"] = "revision_reconciled"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    state = tmp_path / ".agentic_engineering_os_px/processing-order/release-identity.json"
    state.write_text(
        json.dumps(
            {
                "campaign_id": config.predecessor_id,
                "state": "active",
                "apply_count": 1,
                "identity": {"release_identity_sha256": "a" * 64},
                "active_claim": None,
                "stages": {
                    name: {"status": "pending", "claim_id": None}
                    for name in (
                        "sections",
                        "full_profile",
                        "validate",
                        "package",
                        "install",
                        "installed_operational",
                        "certify",
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runtime.release_campaign.release_campaign_status",
        lambda root, verify_source=False: {
            "valid": not verify_source,
            "errors": ["drift"] if verify_source else [],
        },
    )
    assert check(config, "archive_clear")["valid"] is True


def test_archive_check_allows_exact_phase_source_invalid_retained_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, "archive_clear")
    state_dir = tmp_path / ".agentic_engineering_os_px/processing-order"
    repair = state_dir / "repair-campaign.json"
    repair_value = json.loads(repair.read_text(encoding="utf-8"))
    repair_value["phase"] = "repair_frozen"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    state = state_dir / "release-identity.json"
    state.write_text(
        json.dumps({
            "campaign_id": config.predecessor_id,
            "state": "active",
            "apply_count": 1,
            "identity": {"release_identity_sha256": "a" * 64},
            "active_claim": None,
            "stages": {
                name: {
                    "status": "passed" if index < 6 else "pending",
                    "claim_id": None,
                }
                for index, name in enumerate((
                    "sections", "full_profile", "validate", "package", "install",
                    "installed_operational", "certify",
                ))
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runtime.release_campaign.release_campaign_status",
        lambda root, verify_source=False: {
            "valid": not verify_source,
            "errors": ["source drift"] if verify_source else [],
        },
    )
    assert check(config, "archive_clear")["valid"] is True

    repair_value["phase"] = "installed_operational"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    assert check(config, "archive_clear")["valid"] is True

    repair_value["phase"] = "installed"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    assert check(config, "archive_clear")["valid"] is False

    repair_value["phase"] = "repair_frozen"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    monkeypatch.setattr(
        "runtime.release_campaign.release_campaign_status",
        lambda root, verify_source=False: {"valid": True, "errors": []},
    )
    assert check(config, "archive_clear")["valid"] is False


def test_archive_effect_routes_unused_invalid_identity_to_canonical_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, "archive_clear")
    repair = tmp_path / ".agentic_engineering_os_px/processing-order/repair-campaign.json"
    repair_value = json.loads(repair.read_text(encoding="utf-8"))
    repair_value["phase"] = "revision_reconciled"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    state = tmp_path / ".agentic_engineering_os_px/processing-order/release-identity.json"
    value = json.loads(state.read_text(encoding="utf-8"))
    value.update(
        state="active",
        apply_count=1,
        identity={"release_identity_sha256": "a" * 64},
        stages={
            name: {"status": "pending", "claim_id": None}
            for name in (
                "sections",
                "full_profile",
                "validate",
                "package",
                "install",
                "installed_operational",
                "certify",
            )
        },
    )
    state.write_text(json.dumps(value), encoding="utf-8")
    calls: list[str] = []

    def supersede(root: Path, *, campaign_id: str, reason: str) -> dict[str, object]:
        calls.append(campaign_id)
        return {"valid": True, "superseded_archive": "archive.json"}

    monkeypatch.setattr(
        "runtime.release_campaign.supersede_invalid_release_identity", supersede
    )
    monkeypatch.setattr(
        "runtime.release_campaign.release_campaign_status",
        lambda root, verify_source=False: {
            "valid": not verify_source,
            "errors": ["drift"] if verify_source else [],
        },
    )
    rewinds: list[Path] = []
    monkeypatch.setattr(
        "runtime.release_campaign.rewind_invalid_release_identity_reconciliation",
        lambda root: rewinds.append(root) or {"valid": True},
    )
    receipt = ProductionEffects().execute("archive_clear", config)
    assert receipt["valid"] is True
    assert calls == [config.candidate_id]
    assert rewinds == [config.root]


def test_archive_effect_routes_retained_passes_to_active_supersession(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, "archive_clear")
    state_dir = tmp_path / ".agentic_engineering_os_px/processing-order"
    repair = state_dir / "repair-campaign.json"
    repair_value = json.loads(repair.read_text(encoding="utf-8"))
    repair_value["phase"] = "installed_operational"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    state = state_dir / "release-identity.json"
    value = json.loads(state.read_text(encoding="utf-8"))
    value.update(
        state="active",
        apply_count=1,
        identity={"release_identity_sha256": "a" * 64},
        stages={
            name: {
                "status": "passed" if index < 6 else "pending",
                "claim_id": None,
            }
            for index, name in enumerate((
                "sections", "full_profile", "validate", "package", "install",
                "installed_operational", "certify",
            ))
        },
    )
    state.write_text(json.dumps(value), encoding="utf-8")
    calls: list[str] = []
    rewinds: list[Path] = []
    monkeypatch.setattr(
        "runtime.release_campaign.rewind_invalid_active_release_campaign_repair",
        lambda root: rewinds.append(root) or {"valid": True},
    )
    monkeypatch.setattr(
        "runtime.release_campaign.supersede_invalid_active_release_campaign",
        lambda root, *, campaign_id, reason: calls.append(campaign_id)
        or {"valid": True, "superseded_archive": "archive.json"},
    )
    monkeypatch.setattr(
        "runtime.release_campaign.supersede_invalid_release_identity",
        lambda *args, **kwargs: pytest.fail("unused-identity superseder called"),
    )
    monkeypatch.setattr(
        "runtime.release_campaign.rewind_invalid_release_identity_reconciliation",
        lambda root: pytest.fail("unused-identity rewind called"),
    )

    receipt = ProductionEffects().execute("archive_clear", config)
    assert receipt["valid"] is True
    assert calls == [config.candidate_id]
    assert rewinds == [config.root]


def test_archive_check_allows_failed_stage_at_its_exact_repair_phase(
    tmp_path: Path,
) -> None:
    config = fixture(tmp_path, "archive_clear")
    repair = tmp_path / ".agentic_engineering_os_px/processing-order/repair-campaign.json"
    repair_value = json.loads(repair.read_text(encoding="utf-8"))
    repair_value["phase"] = "revision_reconciled"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    state = tmp_path / ".agentic_engineering_os_px/processing-order/release-identity.json"
    state.write_text(
        json.dumps(
            {
                "campaign_id": config.predecessor_id,
                "state": "failed",
                "apply_count": 1,
                "identity": {"release_identity_sha256": "a" * 64},
                "active_claim": None,
                "stages": {
                    name: {
                        "status": "failed" if name == "sections" else "pending",
                        "claim_id": "claim" if name == "sections" else None,
                    }
                    for name in (
                        "sections",
                        "full_profile",
                        "validate",
                        "package",
                        "install",
                        "installed_operational",
                        "certify",
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    assert check(config, "archive_clear")["valid"] is True


def test_archive_effect_rewinds_failed_stage_before_canonical_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, "archive_clear")
    repair = tmp_path / ".agentic_engineering_os_px/processing-order/repair-campaign.json"
    repair_value = json.loads(repair.read_text(encoding="utf-8"))
    repair_value["phase"] = "revision_reconciled"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    rewinds: list[Path] = []
    successors: list[str] = []
    monkeypatch.setattr(
        "runtime.release_campaign.rewind_failed_release_campaign_repair",
        lambda root: rewinds.append(root) or {"valid": True},
    )
    monkeypatch.setattr(
        "runtime.release_campaign.supersede_failed_release_campaign",
        lambda root, *, campaign_id, reason: successors.append(campaign_id)
        or {"valid": True, "superseded_archive": "archive.json"},
    )
    receipt = ProductionEffects().execute("archive_clear", config)
    assert receipt["valid"] is True
    assert rewinds == [config.root]
    assert successors == [config.candidate_id]


def test_child_resource_postcondition_allows_only_exact_supervised_self(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, "archive_clear")
    ledger = tmp_path / ".agentic_engineering_os_px/resource-lifecycle/ledger.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "resources": [
                    {
                        "resource_id": "self-process",
                        "project_id": "fixture",
                        "lane_id": "fixture",
                        "classification": "ephemeral",
                        "created_at": "2026-09-12T00:00:00+00:00",
                        "last_activity_at": "2026-09-12T00:00:00+00:00",
                        "expected_cleanup_event": "exit",
                        "retention_required": False,
                        "active": True,
                        "resource_type": "process",
                        "pid": 123,
                        "run_id": config.candidate_id,
                        "creator": "scripts.run_release_candidate",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PX_RELEASE_OWNER_RUN_ID", config.candidate_id)
    assert resource_postcondition(config)["valid"] is True
    value = json.loads(ledger.read_text(encoding="utf-8"))
    value['resources'].append({**value['resources'][0], 'resource_id': 'active-path', 'resource_type': 'path', 'pid': None})
    ledger.write_text(json.dumps(value), encoding='utf-8')
    assert resource_postcondition(config)["valid"] is False
    value['resources'].pop()
    value["resources"][0]["pid"] = 456
    ledger.write_text(json.dumps(value), encoding="utf-8")
    assert resource_postcondition(config)["valid"] is True
    monkeypatch.setenv("PX_RELEASE_OWNER_RUN_ID", "other-candidate")
    assert resource_postcondition(config)["valid"] is False


def test_command_timeout_closes_owned_process_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, "full_profile")
    waits = 0
    cleanup_calls: list[list[str]] = []

    class Process:
        pid = 321

        def wait(self, timeout: int) -> int:
            nonlocal waits
            waits += 1
            if waits == 1:
                raise subprocess.TimeoutExpired(["owner"], timeout)
            return 1

        def poll(self) -> None:
            return None

    monkeypatch.setattr(
        "scripts.run_release_stage_owner.subprocess.Popen", lambda *args, **kwargs: Process()
    )
    monkeypatch.setattr(
        "scripts.run_release_stage_owner.subprocess.run",
        lambda argv, **kwargs: cleanup_calls.append(argv)
        or type("Result", (), {"returncode": 0})(),
    )
    monkeypatch.setattr("scripts.run_release_stage_owner.os.name", "nt")

    with pytest.raises(OwnerBlocked, match="timed out after 1 seconds"):
        ProductionEffects().command(
            config, "full_profile", ["owner"], timeout_seconds=1
        )
    assert cleanup_calls == [["taskkill", "/PID", "321", "/T", "/F"]]
    assert waits == 2


def test_installed_extension_listing_isolates_host_vscode_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = fixture(tmp_path, "install")
    observed: dict[str, object] = {}
    monkeypatch.setenv("VSCODE_IPC_HOOK", "host-instance")
    monkeypatch.setenv("VSCODE_CWD", "host-workspace")

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["argv"] = list(argv)
        observed["environment"] = dict(kwargs["env"])  # type: ignore[arg-type]
        user_data = Path(argv[argv.index("--user-data-dir") + 1])
        observed["user_data"] = user_data
        assert user_data.is_dir()
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="mountain-nomad-bc.pacify-x-vscode@0.6.85\n",
            stderr="",
        )

    monkeypatch.setattr(
        "scripts.run_release_stage_owner.subprocess.run", fake_run
    )
    result = ProductionEffects().list_installed_extensions(config)

    argv = observed["argv"]
    assert isinstance(argv, list)
    assert argv[argv.index("--extensions-dir") + 1] == str(
        config.installed_dir.parent
    )
    environment = observed["environment"]
    assert isinstance(environment, dict)
    assert not any(str(key).upper().startswith("VSCODE_") for key in environment)
    assert not Path(observed["user_data"]).exists()  # type: ignore[arg-type]
    assert result.returncode == 0


def test_identity_uses_precommitted_head_and_one_annotated_retag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = fixture(tmp_path, "identity")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.7.0"\n', encoding="utf-8"
    )
    calls: list[tuple[str, ...]] = []

    class GitEffects(ProductionEffects):
        def git_add_paths(self, config: Config, paths: tuple[str, ...]) -> None:
            calls.append(("add-pathspec", *paths))

        def git(self, config: Config, *args: str) -> str:
            calls.append(args)
            if args[:3] == ("diff", "--cached", "--name-only"):
                return ""
            if args[:2] == ("rev-list", "-n"):
                return (
                    "0" * 40
                    if len([call for call in calls if call[:2] == ("rev-list", "-n")])
                    == 1
                    else "1" * 40
                )
            if args[:2] == ("cat-file", "-t"):
                return "tag"
            if args[:2] == ("rev-parse", "HEAD"):
                return "1" * 40
            if args[:2] == ("rev-parse", "@{u}"):
                return "1" * 40
            return ""

    monkeypatch.setattr(
        "runtime.release_campaign.apply_release_identity",
        lambda root: {
            "valid": True,
            "identity": {
                "release_identity_sha256": "a" * 64,
                "source_product_digest": "b" * 64,
                "source_harness_digest": "c" * 64,
            },
        },
    )
    dirty_calls = iter(
        (
            {
                "blocking_paths": [],
                "mutable_control_paths": [],
                "classifier_errors": [],
            },
            {
                "blocking_paths": [],
                "mutable_control_paths": [],
                "classifier_errors": [],
            },
        )
    )
    monkeypatch.setattr(
        "runtime.release_identity._release_dirty_state", lambda root: next(dirty_calls)
    )
    result = GitEffects().identity(config)
    assert result["valid"] is True
    assert ("add-pathspec",) in calls
    tag_call = next(call for call in calls if call[:4] == ("tag", "-f", "-a", "v0.7.0"))
    assert tag_call[4:6] == ("-m", f"v0.7.0 {config.candidate_id}")
    assert not any(call[:1] == ("commit",) for call in calls)


def test_git_add_paths_streams_large_nul_delimited_pathspec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = fixture(tmp_path, "identity")
    paths = tuple(f"bulk/path-{index:05d}.txt" for index in range(4_000))
    observed: dict[str, object] = {}
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        if argv[:2] == ["git", "check-ignore"]:
            return subprocess.CompletedProcess(argv, 1, b"", b"")
        if argv[:2] == ["git", "add"]:
            observed["argv"] = argv
            observed["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ProductionEffects().git_add_paths(config, paths)
    assert observed["argv"] == [
        "git", "add", "--pathspec-from-file=-", "--pathspec-file-nul"
    ]
    payload = observed["input"]
    assert isinstance(payload, bytes)
    assert payload.count(b"\0") == len(paths)
    assert payload.startswith(paths[0].encode() + b"\0")
    assert payload.endswith(paths[-1].encode() + b"\0")
    assert calls[0] == ["git", "diff", "--cached", "--quiet", "--exit-code"]


def test_git_add_paths_rejects_ignored_source_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = fixture(tmp_path, "identity")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        if argv[:2] == ["git", "check-ignore"]:
            return subprocess.CompletedProcess(argv, 0, b"ignored.txt\0", b"")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(OwnerBlocked, match="contains ignored paths"):
        ProductionEffects().git_add_paths(config, ("ignored.txt",))
    assert not any(call[:2] == ["git", "add"] for call in calls)


def test_git_add_failure_restores_the_initially_empty_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = fixture(tmp_path, "identity")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        if argv[:2] == ["git", "check-ignore"]:
            return subprocess.CompletedProcess(argv, 1, b"", b"")
        if argv[:2] == ["git", "add"]:
            return subprocess.CompletedProcess(argv, 1, b"", b"staging failed")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(OwnerBlocked, match="staging failed"):
        ProductionEffects().git_add_paths(config, ("source.txt",))
    assert ["git", "reset", "--mixed", "HEAD"] in calls


def test_identity_requires_exact_mutable_control_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = fixture(tmp_path, "identity")
    config.path_manifest.write_text(
        json.dumps(
            {
                "schema_version": "px.release-identity-path-manifest/1.0",
                "candidate_id": config.candidate_id,
                "paths": [],
                "mutable_paths": ["registry/operational_gap_ledger.jsonl"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runtime.release_identity._release_dirty_state",
        lambda root: {
            "blocking_paths": [],
            "mutable_control_paths": ["registry/operational_gap_ledger.snapshot.json"],
            "classifier_errors": [],
        },
    )
    with pytest.raises(OwnerBlocked, match="mutable control changes differ"):
        ProductionEffects().identity(config)


def test_failed_precheck_never_calls_effects(tmp_path: Path) -> None:
    config = fixture(tmp_path, "install")
    config.artifact.write_bytes(b"changed")
    effects = FakeEffects()
    with pytest.raises(OwnerBlocked, match="artifact identity"):
        run(config, "install", effects)
    assert effects.executed == []


def test_config_file_is_parameterized_and_strict(tmp_path: Path) -> None:
    expected = fixture(tmp_path, "archive_clear")
    raw = {
        "schema_version": "px.release-stage-owner-config/1.0",
        "root": str(tmp_path),
        "candidate_id": expected.candidate_id,
        "predecessor_id": expected.predecessor_id,
        "artifact": {
            "path": "candidate.vsix",
            "sha256": expected.artifact_sha256,
            "size": expected.artifact_size,
            "mtime_ns": expected.artifact_mtime_ns,
            "entry_count": 1,
        },
        "evidence_dir": "evidence",
        "log_dir": "logs",
        "identity": {
            "path_manifest": "manifest.json",
            "commit_message": "Freeze final100",
            "release_tag": "v0.7.0",
            "prior_tag_target": "0" * 40,
        },
        "install": {
            "directory": str(tmp_path / "installed"),
            "code_command": str(tmp_path / "code.cmd"),
            "tree_digest": "b" * 64,
            "version": "0.6.85",
            "entry_count": 1,
        },
    }
    path = tmp_path / "owner.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert Config.load(path).release_tag == "v0.7.0"
    raw["artifact"]["sha256"] = "not-a-digest"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(OwnerBlocked, match="incomplete exact"):
        Config.load(path)


@pytest.mark.parametrize("shape", ["relative", "absolute", "mixed"])
def test_release_admission_matches_physical_scopes(tmp_path, shape):
    from tests.test_publication_custody_guard import _root, _admit
    from runtime.release_process_custody import require_release_admission
    root = _root(tmp_path)
    scopes = ["registry"] if shape == "relative" else [str(root / "registry")]
    if shape == "mixed":
        scopes.append("evidence")
    admission = _admit(root, scopes, effects=("read", "write", "execute"))
    result = require_release_admission(root, admission, (("write", "registry/receipt.json"), ("read", "registry"), ("execute", "runtime")))
    assert result["event_id"] == admission


@pytest.mark.parametrize("scope,target", [("registry-sibling", "registry/output.json"), ("registry/child", "registry/output.json"), ("registry", "registry/../unadmitted/output.json")])
@pytest.mark.parametrize("absolute", [False, True])
def test_release_admission_rejects_uncovered_physical_target(tmp_path, scope, target, absolute):
    from tests.test_publication_custody_guard import _root, _admit
    from runtime.release_process_custody import require_release_admission
    root = _root(tmp_path)
    admission = _admit(root, [str(root / scope) if absolute else scope], effects=("read", "write", "execute"))
    with pytest.raises(PermissionError):
        require_release_admission(root, admission, (("write", target),))


_VSIX_FIXTURE_WRAPPER = r"""
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const actualRequire = require('node:module').createRequire(process.argv[1]);
const root = process.argv[2], mode = process.argv[3];
const artifact = path.join(root, 'dist', 'z-fixture-0.1.0.vsix');
let raced = false;
const fixtureFs = mode === 'race' ? { ...fs, writeFileSync(destination, ...args) {
  if (String(destination) === artifact && !raced) {
    fs.writeFileSync(artifact, 'retained competing artifact'); raced = true;
  }
  return fs.writeFileSync(destination, ...args);
}} : fs;
const localRequire = name => name === 'fs' ? fixtureFs : actualRequire(name);
const fixtureModule = { exports: {} };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  require: localRequire, module: fixtureModule, exports: fixtureModule.exports,
  __dirname: path.join(root, 'scripts'), __filename: path.join(root, 'scripts', 'package-vsix.js'),
  process, Buffer, console
});
if (typeof fixtureModule.exports.packageVsix === 'function') fixtureModule.exports.packageVsix(root);
"""


def _run_vsix_fixture(tmp_path, mode):
    import shutil
    extension = tmp_path / 'extension'
    (extension / 'src').mkdir(parents=True)
    (extension / 'src/extension.js').write_text('module.exports = { fixture: "current bundle" };\n')
    (extension / 'package.json').write_text(json.dumps({
        'name': 'z-fixture', 'version': '0.1.0', 'publisher': 'fixture',
        'displayName': 'Fixture', 'description': 'Disposable package fixture',
        'engines': {'vscode': '^1.132.0'},
    }))
    if mode == 'duplicate':
        (extension / 'src/extension.bundle.js').write_text('stale generated bundle')
    if mode == 'budget':
        issued = tmp_path / '.agentic_engineering_os_px/quarantine/release-artifacts/vscode'
        issued.mkdir(parents=True)
        for index in range(4097):
            (issued / f'a{index:05d}.txt').write_bytes(b'')
        (issued / 'z-fixture-0.1.0.vsix').write_bytes(b'issued version')
    script = Path(__file__).parents[1] / 'extension/scripts/package-vsix.js'
    completed = subprocess.run([shutil.which('node'), '-e', _VSIX_FIXTURE_WRAPPER,
                                str(script), str(extension), mode],
                               cwd=extension, text=True, capture_output=True, timeout=60)
    return extension, completed


def test_vsix_packaging_has_one_current_generated_bundle(tmp_path):
    import zipfile
    extension, completed = _run_vsix_fixture(tmp_path, 'duplicate')
    assert completed.returncode == 0, completed.stderr
    with zipfile.ZipFile(extension / 'dist/z-fixture-0.1.0.vsix') as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert archive.testzip() is None
        bundle = archive.read('extension/src/extension.bundle.js')
        assert b'current bundle' in bundle and b'stale generated' not in bundle


def test_vsix_packaging_preserves_a_racing_artifact(tmp_path):
    extension, completed = _run_vsix_fixture(tmp_path, 'race')
    assert completed.returncode != 0
    assert (extension / 'dist/z-fixture-0.1.0.vsix').read_bytes() == b'retained competing artifact'
    assert not (extension / 'SHA256SUMS.txt').exists()


def test_vsix_packaging_refuses_incomplete_issued_version_inventory(tmp_path):
    extension, completed = _run_vsix_fixture(tmp_path, 'budget')
    assert completed.returncode != 0
    assert not (extension / 'dist/z-fixture-0.1.0.vsix').exists()
    assert not (extension / 'SHA256SUMS.txt').exists()


def test_current_stage_command_refuses_uncommissioned_host_before_effects(tmp_path, monkeypatch):
    from dataclasses import replace
    value = replace(fixture(tmp_path, "package"), identity_kind="standalone_current_campaign")
    monkeypatch.delenv("PX_GREMLIN_RECOVERY_VERIFIER", raising=False)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    def forbidden(*args, **kwargs):
        pytest.fail("current release reached legacy unsupervised process launch")
    # Replace this caller's module binding, not the global subprocess module:
    # ProcessSupervisor defines a Popen subclass when first imported.
    from types import SimpleNamespace
    monkeypatch.setattr("scripts.run_release_stage_owner.subprocess",
                        SimpleNamespace(**{**vars(subprocess), "Popen": forbidden}))
    with pytest.raises(PermissionError, match="commissioned Gremlin host verifier"):
        ProductionEffects().command(value, "package-build", ["node", "fixture.js"], timeout_seconds=60)
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert not value.log_dir.exists()


def test_current_stage_command_dispatches_exact_native_custody_owner(tmp_path, monkeypatch):
    from dataclasses import replace
    value = replace(fixture(tmp_path, "package"), identity_kind="standalone_current_campaign")
    seen = []
    expected = {"valid": True, "fixture_only": True}
    def native(*args, **kwargs):
        seen.append((args, kwargs))
        return expected
    monkeypatch.setattr("runtime.release_process_custody.run_release_command", native)
    result = ProductionEffects().command(value, "package-build", ["node", "fixture.js"], timeout_seconds=60)
    assert result is expected
    assert seen == [((value, "package-build", ["node", "fixture.js"]), {"timeout_seconds": 60})]
    assert not value.log_dir.exists()


@pytest.mark.parametrize("kind", ["portable-alias", "oversized-member", "unsupported-compression", "valid"])
def test_package_audit_refuses_unbounded_or_nonportable_archive(tmp_path, monkeypatch, kind):
    from dataclasses import replace
    import zipfile
    config = fixture(tmp_path, "package")
    with zipfile.ZipFile(config.artifact, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if kind == "portable-alias":
            archive.writestr("extension/Foo.js", b"a")
            archive.writestr("extension/foo.js", b"b")
        elif kind == "oversized-member":
            archive.writestr("extension/large.bin", b"x" * (32 * 1024 * 1024 + 1))
        elif kind == "unsupported-compression":
            archive.writestr("extension/file.js", b"a", compress_type=zipfile.ZIP_BZIP2)
        else:
            archive.writestr("extension/file.js", b"a")
    image = config.artifact.read_bytes()
    with zipfile.ZipFile(config.artifact) as archive:
        count = len(archive.infolist())
    config = replace(config, artifact_sha256=hashlib.sha256(image).hexdigest(),
                     artifact_size=len(image), artifact_mtime_ns=config.artifact.stat().st_mtime_ns,
                     zip_entry_count=count)
    monkeypatch.setattr("scripts.run_release_stage_owner.release", lambda config: {"identity": {
        "release_identity_sha256": "a" * 64, "source_product_digest": "b" * 64,
        "source_harness_digest": "c" * 64}})
    if kind == "valid":
        result = ProductionEffects().package_audit(config, {"claim_id": "fixture-only"})
        assert result["valid"] is True and result["crc_clean"] is True
        assert result["artifact_rebuilt"] is False
    else:
        with pytest.raises(ValueError, match="alias|budget|unsupported"):
            ProductionEffects().package_audit(config, {"claim_id": "fixture-only"})
    assert config.artifact.read_bytes() == image


def _current_realization_fixture(tmp_path, monkeypatch, failure=None):
    """Real native claims/MAC/archive; fixture command seam is NOT host commissioning."""
    import os
    from types import SimpleNamespace
    import shutil
    import sys
    from tests.test_publication_custody_guard import _root, _checkpoint, GAP
    from tests.release_preflight_testkit import minimal_product
    from runtime.release_campaign import (clear_release_identity, apply_release_identity, claim_release_stage,
        finish_release_stage, REPAIR_CAMPAIGN_PATH)
    from runtime.release_source_identity import release_configuration_relative
    from runtime.source_freeze import freeze_source
    from runtime.studio_authority import StudioAuthorityStore
    from runtime.archive_io import read_archive_bytes, validated_zip
    from runtime.process_supervisor import ProcessSupervisor
    from runtime.resource_lifecycle import ResourceManager
    from scripts import run_release_candidate as driver
    from scripts.run_release_stage_owner import private_installation_root
    root = _root(tmp_path); _checkpoint(root); minimal_product(root)
    extension = root / 'extension'; (extension / 'src').mkdir(parents=True)
    (extension / 'scripts').mkdir()
    (extension / 'src/extension.js').write_text('module.exports = { fixture: "current bundle" };\n')
    (extension / 'package.json').write_text(json.dumps({'name':'z-fixture','publisher':'fixture','version':'0.9.0',
        'displayName':'Disposable fixture','description':'Unit-test package only','engines':{'vscode':'^1.132.0'}}))
    source_root = Path(__file__).resolve().parents[1]
    shutil.copyfile(source_root / 'extension/scripts/package-vsix.js', extension / 'scripts/package-vsix.js')
    (root / 'pyproject.toml').write_text(chr(10).join(('[project]', 'name="disposable-package-fixture"', 'version="0.9.0"', '')))
    (root / 'policies/rev1xx-validation.json').write_text(json.dumps({'schema_version':'px.validation-basis/1.0',
        'basis':'current_implementation','authority':'OWNER-FRESH-VALIDATION-001','campaign_id':'disposable-realization-repair'}))
    policy_path = root / 'policies/release-artifact-policy.json'
    policy = json.loads(policy_path.read_text()); policy['product_roots'].append('extension')
    policy['product_root_files']=['pyproject.toml']
    policy['control_output_prefixes']=['.agentic_engineering_os_px/', 'registry/operational_gap_ledger.deltas/', 'registry/.lock-recovery-receipts/']
    policy['control_output_paths']=['.agentic_engineering_os_px', 'extension/SHA256SUMS.txt',
        'registry/operational_gap_ledger.jsonl', 'registry/operational_gap_ledger.snapshot.json',
        'registry/operational_gap_ledger.head.json', 'registry/.operational-gap-ledger.lock']
    policy_path.write_text(json.dumps(policy))
    control = root / REPAIR_CAMPAIGN_PATH
    def phase(name):
        control.parent.mkdir(parents=True, exist_ok=True)
        control.write_text(json.dumps({'campaign_id':'disposable-realization-repair','phase':name,
                                     'intake_open':False,'unresolved':[]}))
    (root/'runtime/__init__.py').write_text('')
    (root/'runtime/cli.py').write_text("print('disposable validation workload; not project validation')" + chr(10))
    from runtime.isolated_sandbox import sandbox_off, SANDBOX_POLICY_RELATIVE
    sandbox=root/SANDBOX_POLICY_RELATIVE;sandbox.parent.mkdir(parents=True,exist_ok=True)
    sandbox.write_text(json.dumps(sandbox_off(scope_key=root.as_posix()).as_dict()))
    authority = StudioAuthorityStore(root)
    phase('repair_frozen'); clear_release_identity(root,campaign_id='disposable-unit-release')
    frozen = freeze_source(root,freeze_id='disposable-realization-source',current_campaign=True)
    ref_path = frozen.receipt['receipt_path']
    ref = {'path':ref_path,'sha256':hashlib.sha256((root/ref_path).read_bytes()).hexdigest()}
    phase('revision_reconciled'); apply_release_identity(root,source_freeze_reference=ref)
    for name, after in (('sections','sections_current'),('full_profile','full_profile_passed'),('validate','validated')):
        # Native predecessor fixture states only; no operational/profile acceptance is claimed.
        claim = claim_release_stage(root,name); finish_release_stage(root,stage=name,claim_id=claim['claim_id'],passed=True)
        phase(after)
    host = tmp_path / 'fixture-host'; (host / 'resources/app/out').mkdir(parents=True)
    code = host / ('Code.exe' if os.name == 'nt' else 'code')
    code.write_text('Fixture placeholder; never executed as a host binary.'); (host/'resources/app/out/cli.js').write_text('// fixture only')
    private = root / __import__('runtime.release_source_identity',fromlist=['release_private_installation_relative']).release_private_installation_relative('disposable-unit-release')
    raw = {'schema_version':'px.release-stage-owner-config/2.0','root':str(root),'candidate_id':'disposable-unit-release',
        'predecessor_id':'disposable-previous','artifact':{'state':'planned','path':'extension/dist/z-fixture-0.9.0.vsix',
        'type':'vsix','build_owner':'extension/scripts/package-vsix.js'},
        'identity':{'identity_kind':'standalone_current_campaign','source_freeze':ref},
        'install':{'state':'planned','directory':str(private/'extensions/fixture.z-fixture-0.9.0'),'code_command':str(code)},
        'evidence_dir':'evidence/unit-release','log_dir':'.agentic_engineering_os_px/runtime-core/release/logs'}
    stage_path = root / release_configuration_relative('disposable-unit-release','stage-owner')
    stage_path.parent.mkdir(parents=True); stage_path.write_text(json.dumps(raw))
    stage = Config.load(stage_path)
    automation = driver.Config(root=root,candidate_id=stage.candidate_id,candidate_date='20261114',
        predecessor_campaign_id='disposable-previous',repair_campaign_id='disposable-realization-repair',evidence_prefix='unit',
        artifact=stage.artifact,artifact_sha256='',artifact_size=0,artifact_mtime_ns=0,
        automation_state=root/'.agentic_engineering_os_px/unit-state.json',log_root=stage.log_dir,
        installed_summary=root/'evidence/installed.json',installed_exhaustive_receipt=root/'evidence/walk.json',
        cohesion_dag=root/'unit-dag.json',identity_path_manifest=root/ref['path'],
        timeouts_seconds={name:60 for name in driver.STEP_ORDER},fresh_paths=(stage.evidence_dir,),
        owners={name:((sys.executable,'-B','scripts/run_release_stage_owner.py','--config',stage_path.relative_to(root).as_posix(),
                        '--step',name,'--execute'),) for name in driver.STEP_ORDER},
        identity_kind='standalone_current_campaign',source_freeze_reference=ref,artifact_state='planned')
    monkeypatch.setattr('runtime.release_process_custody.require_release_host', lambda project, **kwargs: SimpleNamespace(fixture_only=True))
    effects = ProductionEffects(); calls=[]
    def command(value, name, argv, *, timeout_seconds):
        calls.append(name)
        if failure == name:
            raise RuntimeError('controlled fixture command failure')
        if name == 'package-build':
            manager = ResourceManager(root/'.agentic_engineering_os_px/resource-lifecycle/ledger.json')
            budgets = {'startup_timeout_seconds':60,'idle_timeout_seconds':60,'total_timeout_seconds':60,
                'graceful_shutdown_seconds':2,'force_shutdown_seconds':5,'stdout_limit_bytes':1048576,'stderr_limit_bytes':1048576}
            process = ProcessSupervisor(manager).run(argv,cwd=root,project_id=str(root),run_id='fixture-package-command',
                lane_id='fixture',creator='pytest',action={'action_id':'fixture-package-build','effects':['process'],
                'allowed_effects':['process'],'owned_paths':[str(root)],'target_paths':[str(root)],
                'budget':budgets,'limits':budgets,'approval':True,'policy_override_requested':False},
                environment={**os.environ,'NODE_PATH':str(source_root/'extension/node_modules')})
            assert process.tree_closed and process.exit_code == 0, process.stderr.text
            text = process.stdout.text
        elif name == 'install-realize':
            value.installed_dir.mkdir(parents=True)
            with validated_zip(read_archive_bytes(value.artifact)) as (archive, rows):
                for row in rows:
                    if not row.is_dir() and row.filename.startswith('extension/'):
                        target=value.installed_dir/row.filename.removeprefix('extension/');target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_bytes(archive.read(row))
                (value.installed_dir/'.vsixmanifest').write_bytes(archive.read('extension.vsixmanifest'))
            package_path=value.installed_dir/'package.json';package=json.loads(package_path.read_text())
            package['__metadata']={'fixture_only':True};package_path.write_text(json.dumps(package));text='Fixture installed\n'
        else:
            assert name == 'install-list';text='fixture.z-fixture@0.9.0\n'
        value.log_dir.mkdir(parents=True,exist_ok=True);log=value.log_dir/f'{value.candidate_id}-{name}.log'
        with log.open('x',encoding='utf-8') as stream:stream.write(text)
        return {'path':value.relative(log),'sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'size':log.stat().st_size,
            'valid':True,'fixture_only':True,'native_recovery_or_operational_acceptance_claimed':False}
    monkeypatch.setattr(effects,'command',command)
    return stage, automation, stage_path, effects, calls, authority, GAP


def test_current_realization_build_install_and_authenticated_readback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from runtime.release_process_custody import require_release_admission
    from scripts import run_release_candidate as driver
    from scripts.run_release_stage_owner import private_installation_root, observe_completed_stages
    stage, automation, path, effects, calls, authority, gap = _current_realization_fixture(tmp_path, monkeypatch)
    from scripts.run_installed_operational_owner import observed_stage_artifact, OwnerBlocked as InstalledBlocked
    with pytest.raises(InstalledBlocked,match='authenticated completed'):
        observed_stage_artifact(stage.root,path,candidate_id=stage.candidate_id,artifact=stage.artifact,manual_identity=(None,None,None))
    before_config=path.read_bytes();governance=driver.LedgerCampaignGovernance(automation,gap)
    package_admission=governance.admit('package');monkeypatch.setenv('PX_RELEASE_ADMISSION_EVENT_ID',package_admission['event_id'])
    journal=driver.Journal(automation);journal.start('package',admission_event_id=package_admission['event_id'],gap_id=gap)
    effects.execute('package',stage);effects.verify('package',stage)
    observed=Config.load(path)
    assert observed.artifact_state == 'observed_current' and observed.install_state == 'planned'
    assert observed.artifact_sha256 == hashlib.sha256(stage.artifact.read_bytes()).hexdigest()
    package_path=stage.evidence_dir/f'{stage.candidate_id}-package.json';original=package_path.read_bytes()
    signed=json.loads(original);assert signed['artifact_rebuilt'] is True and signed['artifact_touched'] is True
    unsigned=dict(signed);unsigned.pop('authentication');package_path.write_text(json.dumps(unsigned))
    with pytest.raises(PermissionError):Config.load(path)
    package_path.write_bytes(original)
    wrong=authority.verify_receipt(signed);wrong['claim_id']='unrelated-native-claim'
    package_path.write_text(json.dumps(authority.sign_receipt(wrong)))
    with pytest.raises(OwnerBlocked,match='native stage/source'):Config.load(path)
    package_path.write_bytes(original)
    journal.finish('package',passed=True,details={'fixture_only':True});governance.settle('package',package_admission,passed=True)
    install_admission=governance.admit('install');monkeypatch.setenv('PX_RELEASE_ADMISSION_EVENT_ID',install_admission['event_id'])
    private=private_installation_root(stage)
    monkeypatch.delenv('PX_RELEASE_INSTALL_ADMISSION_EVENT_ID',raising=False)
    with pytest.raises(PermissionError):effects.execute('install',observed)
    assert not private.exists()
    require_release_admission(stage.root,install_admission['install_event_id'],(('install',str(private)),))
    with pytest.raises(PermissionError):
        require_release_admission(stage.root,install_admission['event_id'],(('install',str(private)),))
    monkeypatch.setenv('PX_RELEASE_INSTALL_ADMISSION_EVENT_ID',install_admission['install_event_id'])
    journal.start('install',admission_event_id=install_admission['event_id'],gap_id=gap)
    effects.execute('install',observed);effects.verify('install',observed)
    journal.finish('install',passed=True,details={'fixture_only':True})
    governance.settle('install',install_admission,passed=True)
    installed=Config.load(path);assert installed.install_state == 'observed_current'
    receipt=json.loads((stage.evidence_dir/f'{stage.candidate_id}-install.json').read_text())
    assert receipt['machine_mutated'] is True and receipt['install_command_executed'] is True
    assert receipt['installed_file_count'] == installed.installable_entry_count
    assert path.read_bytes() == before_config
    assert calls == ['package-build','install-realize','install-list']
    assert observed_stage_artifact(stage.root,path,candidate_id=stage.candidate_id,
        artifact=stage.artifact,manual_identity=(None,None,None)) == (installed.artifact_sha256,installed.artifact_size,installed.artifact_mtime_ns)
    with pytest.raises(InstalledBlocked,match='manual artifact'):
        observed_stage_artifact(stage.root,path,candidate_id=stage.candidate_id,
            artifact=stage.artifact,manual_identity=('0'*64,None,None))
    from types import SimpleNamespace
    from scripts.run_installed_operational_owner import _stage_receipt as operational_receipt
    operational=SimpleNamespace(root=stage.root,candidate_id=stage.candidate_id,artifact=stage.artifact,
        artifact_sha256=installed.artifact_sha256,artifact_size=installed.artifact_size,
        artifact_mtime_ns=installed.artifact_mtime_ns,stage_owner_config=path)
    current=driver.current_observed_configuration(automation)
    assert current.artifact_sha256 == installed.artifact_sha256
    for label in ('package','install'):
        native=__import__('scripts.run_release_stage_owner',fromlist=['release']).release(installed)
        evidence_path=stage.evidence_dir/f'{stage.candidate_id}-{label}.json'
        reference={'path':evidence_path.relative_to(stage.root).as_posix(),'sha256':hashlib.sha256(evidence_path.read_bytes()).hexdigest(),'size':evidence_path.stat().st_size}
        body=driver._validate_stage_receipt(current,reference,
            label=label,identity=native['identity'],expected_claim_id=native['stages'][label]['claim_id'])
        assert body['realization']['owner_command']['fixture_only'] is True
        bound=operational_receipt(operational,evidence_path,label=label,identity=native['identity'],
            claim_id=native['stages'][label]['claim_id'],artifact=body['artifact'])
        assert bound['realization']['stage']==label
        with pytest.raises(InstalledBlocked,match='artifact argument differs'):
            operational_receipt(operational,evidence_path,label=label,identity=native['identity'],
                claim_id=native['stages'][label]['claim_id'],artifact={})


    installed_file=installed.installed_dir/'src/extension.bundle.js';installed_file.write_bytes(b'changed installed bytes')
    with pytest.raises(OwnerBlocked,match='actual installed bytes'):Config.load(path)



@pytest.mark.parametrize('failure', ['package-build','install-realize'])
def test_current_realization_failure_is_terminal_and_preserves_its_attempt(tmp_path, monkeypatch, failure):
    from scripts import run_release_candidate as driver
    from scripts.run_release_stage_owner import release, private_installation_root
    from runtime.resource_lifecycle import ResourceLedger
    stage, automation, path, effects, calls, authority, gap = _current_realization_fixture(tmp_path,monkeypatch,failure)
    governance=driver.LedgerCampaignGovernance(automation,gap)
    admitted=governance.admit('package');monkeypatch.setenv('PX_RELEASE_ADMISSION_EVENT_ID',admitted['event_id'])
    step='package'
    if failure == 'install-realize':
        journal=driver.Journal(automation);journal.start('package',admission_event_id=admitted['event_id'],gap_id=gap)
        effects.execute('package',stage);stage=Config.load(path)
        journal.finish('package',passed=True,details={'fixture_only':True});governance.settle('package',admitted,passed=True)
        admitted=governance.admit('install');monkeypatch.setenv('PX_RELEASE_ADMISSION_EVENT_ID',admitted['event_id'])
        monkeypatch.setenv('PX_RELEASE_INSTALL_ADMISSION_EVENT_ID',admitted['install_event_id']);step='install'
    with pytest.raises(RuntimeError,match='controlled fixture'):
        effects.execute(step,stage)
    native=release(stage);assert native['state']=='failed' and native['stages'][step]['status']=='failed'
    receipt=json.loads((stage.evidence_dir/f'{stage.candidate_id}-{step}.json').read_text())
    assert receipt['valid'] is False and receipt['status']=='failed'
    before=list(calls)
    with pytest.raises((OwnerBlocked,ValueError)):
        effects.execute(step,stage)
    assert calls==before
    if step=='install':
        private=private_installation_root(stage);assert private.is_dir()
        rows=ResourceLedger(stage.root/'.agentic_engineering_os_px/resource-lifecycle/ledger.json').load()
        retained=[row for row in rows if row.path == str(private)]
        assert len(retained)==1 and retained[0].active is False and retained[0].retention_required is True
        assert retained[0].status=='retained'


def test_native_release_setup_failure_releases_only_unlaunched_leases(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from scripts.run_release_candidate import LedgerCampaignGovernance
    from runtime.release_process_custody import run_release_command
    from runtime.scope_lease import ScopeLeaseStore
    from runtime.effect_intent import EffectIntentLedger
    stage, automation, path, effects, calls, authority, gap = _current_realization_fixture(tmp_path,monkeypatch)
    admitted=LedgerCampaignGovernance(automation,gap).admit('validate')
    monkeypatch.setenv('PX_RELEASE_ADMISSION_EVENT_ID',admitted['event_id'])
    monkeypatch.setattr('runtime.release_process_custody.require_release_host',
        lambda root, **kwargs:SimpleNamespace(nanny=SimpleNamespace(gremlin_revision='c'*64)))
    acquire=ScopeLeaseStore.acquire
    def fail_log(self, **kwargs):
        if kwargs['effect']=='write':raise RuntimeError('controlled prelaunch log lease failure')
        return acquire(self,**kwargs)
    monkeypatch.setattr(ScopeLeaseStore,'acquire',fail_log)
    monkeypatch.setattr('runtime.process_supervisor.ProcessSupervisor.run',
        lambda *args,**kwargs:pytest.fail('setup failure must precede process launch'))
    with pytest.raises(RuntimeError,match='controlled prelaunch'):
        run_release_command(stage,'validate',[sys.executable,'-B','-m','runtime.cli','validate'],timeout_seconds=60)
    assert ScopeLeaseStore(stage.root).active(effect='execute') == ()
    ledger=EffectIntentLedger(stage.root);rows=json.loads(ledger.path.read_text())['intents']
    assert len(rows)==1 and rows[0]['state']=='failed'
    assert not (stage.log_dir/f'{stage.candidate_id}-validate.log').exists()


@pytest.mark.parametrize('name', ['install-renamed','package-renamed','validate'])
def test_native_release_role_cannot_hide_an_arbitrary_installer(name, tmp_path):
    from runtime.release_process_custody import assert_release_command_argv
    config=fixture(tmp_path,'package')
    with pytest.raises(PermissionError,match='closed native owner role'):
        assert_release_command_argv(config,name,[str(config.code_command),'--install-extension','unowned.vsix'])



@pytest.mark.skipif(__import__('os').name != 'nt',reason='real pre-release Windows Job custody')
def test_current_release_command_uses_real_job_observer_and_enforcement(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from runtime import release_process_custody as native
    from runtime.gremlin.composition import compose_gremlin_runtime
    from tests.test_gremlin_composition import _identity_store
    from scripts.run_release_candidate import LedgerCampaignGovernance
    original=native.require_release_host
    stage, automation, path, effects, calls, authority, gap = _current_realization_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(native,'require_release_host',original)
    store,identity=_identity_store(); hosts=[]
    def no_recovery(*args):pytest.fail('fixture must never request or claim human recovery approval')
    verifier=SimpleNamespace(verify=no_recovery)
    monkeypatch.setattr(native,'resolve_recovery_verifier_from_environment',lambda:verifier)
    def configured(root,**kwargs):
        # Only protected credential/configuration resolution is replaced.
        # Observation, enforcement, enrollment, Job custody and closure are real.
        host=compose_gremlin_runtime(project_root=root,nanny_authority_id='nanny',
            recovery_authority_id='fixture-independent-recovery',identity_store=store,runtime_identity=identity,
            recovery_verifier=kwargs['recovery_verifier'],observers=kwargs['observers'],
            supervisor_backend=kwargs['supervisor_backend'])
        hosts.append(host);return host
    monkeypatch.setattr(native,'load_configured_gremlin_runtime',configured)
    admitted=LedgerCampaignGovernance(automation,gap).admit('validate')
    monkeypatch.setenv('PX_RELEASE_ADMISSION_EVENT_ID',admitted['event_id'])
    try:
        result=native.run_release_command(stage,'validate',[sys.executable,'-B','-m','runtime.cli','validate'],timeout_seconds=60)
    except PermissionError as error:
        from runtime.source_freeze import verify_freeze
        raise AssertionError(verify_freeze(stage.root,relative=Path(stage.source_freeze_reference['path']))) from error
    assert result['valid'] is True and result['returncode']==0
    assert result['physical_closure']['closure_method']=='native-windows-job-zero'
    assert result['enrollment']['containment_proven'] is True
    assert result['enrollment']['process_identity']['policy_profile']=='release-command'
    assert result['admission_event_id']==admitted['event_id']
    text=(stage.root/result['path']).read_text();assert 'disposable validation workload' in text
    assert all(not host.nanny.registry.active() for host in hosts)
