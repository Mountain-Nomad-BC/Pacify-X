from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path

import pytest

from scripts.run_installed_operational_owner import (
    Config,
    MemberPaths,
    OwnerBlocked,
    execute,
    plan,
)


IDENTITY_SHA = "1" * 64
PRODUCT_SHA = "2" * 64
HARNESS_SHA = "3" * 64


@pytest.mark.parametrize("missing_leaf", [False, True])
def test_owner_preserves_link_provenance_before_resolving_member_path(tmp_path, missing_leaf):
    from scripts.run_installed_operational_owner import _inside

    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"host does not permit a disposable directory symlink: {error}")
    if not missing_leaf:
        (real / "receipt.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OwnerBlocked, match="link|alias|unsafe"):
        _inside(tmp_path, alias / "receipt.json", "member receipt")
    assert alias.is_symlink()


def test_owner_publication_preserves_a_concurrent_receipt(tmp_path, monkeypatch):
    from scripts.run_installed_operational_owner import _write_json

    target = tmp_path / "summary.json"
    original_open = Path.open
    competitor = b'{"owner":"other-run"}\n'
    injected = False

    def racing_open(path, mode="r", *args, **kwargs):
        nonlocal injected
        if not injected and "x" in mode and path.parent == target.parent:
            injected = True
            with original_open(target, "wb") as stream:
                stream.write(competitor)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", racing_open)
    with pytest.raises((OwnerBlocked, FileExistsError)):
        _write_json(target, {"owner": "this-run"})
    assert target.read_bytes() == competitor


def test_owner_rejects_unserializable_summary_before_creating_directories(tmp_path):
    from scripts.run_installed_operational_owner import _write_json

    target = tmp_path / "unallocated" / "summary.json"
    with pytest.raises((ValueError, TypeError)):
        _write_json(target, {"invalid": object()})
    assert not target.parent.exists()


def test_owner_rejects_nonfinite_summary_before_publication(tmp_path):
    from scripts.run_installed_operational_owner import _write_json

    target = tmp_path / "summary.json"
    with pytest.raises(ValueError):
        _write_json(target, {"invalid": float("nan")})
    assert not target.exists()


@pytest.mark.parametrize("mutation", ["append", "quoted-text", "substitution"])
def test_ubuntu_command_rejects_additional_shell_actions_before_any_effect(tmp_path, mutation):
    from dataclasses import replace

    config = _config(tmp_path)
    shell = config.ubuntu.command[-1]
    if mutation == "append":
        shell += "; echo unexpected-action"
    elif mutation == "quoted-text":
        shell = "echo " + shlex.quote(shell)
    else:
        shell = "TMPDIR=$(echo unexpected-action) " + shell
    config = replace(config, ubuntu=replace(config.ubuntu, command=(*config.ubuntu.command[:-1], shell)))
    with pytest.raises(OwnerBlocked, match="Ubuntu smoke command"):
        plan(config)


def test_ubuntu_command_accepts_exact_builder_working_directory_and_quoted_temp_root(tmp_path):
    from dataclasses import replace
    from scripts.run_installed_operational_owner import _wsl_path

    config = _config(tmp_path)
    shell = "cd " + shlex.quote(_wsl_path(config.root)) + " && TMPDIR=" + shlex.quote("/tmp/private tmp") + " " + config.ubuntu.command[-1]
    config = replace(config, ubuntu=replace(config.ubuntu, command=(*config.ubuntu.command[:-1], shell)))
    assert plan(config)["valid"] is True


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _config(tmp_path: Path) -> Config:
    artifact = tmp_path / "candidate.vsix"
    artifact.write_bytes(b"immutable candidate")
    observed = artifact.stat()
    candidate = "pacify-x-certification-20260906-final100-single"
    package_claim = f"release-stage:{candidate}:package:one"
    install_claim = f"release-stage:{candidate}:install:one"
    identity = {
        "release_identity_sha256": IDENTITY_SHA,
        "source_product_digest": PRODUCT_SHA,
        "source_harness_digest": HARNESS_SHA,
    }
    artifact_binding = {
        "path": "candidate.vsix",
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "size": observed.st_size,
    }
    _write(
        tmp_path / ".agentic_engineering_os_px/processing-order/release-identity.json",
        {
            "schema_version": "px.release-campaign/1.0",
            "campaign_id": candidate,
            "state": "active",
            "apply_count": 1,
            "active_claim": None,
            "identity": identity,
            "stages": {
                "package": {"status": "passed", "claim_id": package_claim},
                "install": {"status": "passed", "claim_id": install_claim},
                "installed_operational": {"status": "pending", "claim_id": None},
            },
        },
    )
    _write(
        tmp_path / ".agentic_engineering_os_px/processing-order/repair-campaign.json",
        {
            "schema_version": "px.repair-campaign/1.0",
            "phase": "installed",
            "intake_open": False,
            "unresolved": [],
        },
    )
    _write(
        tmp_path / "registry/engine_identity.json",
        {
            "schema_version": "px.engine-identity/1.0",
            "tree_sha256": "4" * 64,
            "file_total": 1,
        },
    )
    common = {
        "campaign_id": candidate,
        **identity,
        "artifact": artifact_binding,
        "valid": True,
    }
    _write(
        tmp_path / "package.json",
        {
            **common,
            "schema_version": "px.release-stage-evidence/1.0",
            "claim_id": package_claim,
            "stage": "package",
            "status": "passed",
            "attempt_count": 1,
            "artifact_mtime_ns": observed.st_mtime_ns,
            "entry_count": 2,
            "unique_entry_count": 2,
            "crc_clean": True,
            "unsafe_path_count": 0,
            "encrypted_count": 0,
            "symlink_count": 0,
            "artifact_unchanged": True,
            "artifact_rebuilt": False,
            "artifact_touched": False,
            "resource_count": 0,
            "active_processes": 0,
            "cleanup_failures": 0,
        },
    )
    _write(
        tmp_path / "install.json",
        {
            **common,
            "schema_version": "px.install-audit-denominator/1.0",
            "claim_id": install_claim,
            "install_claim_id": install_claim,
            "listed_owned_versions": [
                "mountain-nomad-bc.pacify-x-vscode@0.6.85"
            ],
            "exact_version_count": 1,
            "installable_entry_count": 2,
            "installed_file_count": 2,
            "verified_byte_identical_entries": 1,
            "normalized_package_json_entries": 1,
            "missing": [],
            "extra": [],
            "mismatches": [],
            "crc_failures": [],
            "installed_symlinks_before": [],
            "installed_symlinks_after": [],
            "tree_digest_before": "5" * 64,
            "tree_digest_after": "5" * 64,
            "installed_tree_unchanged": True,
            "machine_mutated": False,
            "install_command_executed": False,
            "release_stage": "passed",
            "processing_phase": "installed",
            "resource_count": 0,
            "active_processes": 0,
            "cleanup_failures": 0,
            "audit_valid": True,
        },
    )

    def member(name: str, *, exhaustive: bool = False) -> MemberPaths:
        receipt = tmp_path / f"{name}.receipt.json"
        lifecycle = None if exhaustive else tmp_path / f"{name}.lifecycle.json"
        if exhaustive:
            command = (
                "node",
                "extension/scripts/run-isolated-current-source-walk.js",
                "--post-audit-long-running",
                "--vsix",
                str(artifact),
                "--output",
                str(receipt.parent),
                "--report",
                str(tmp_path / f"{name}.report.json"),
            )
        elif name == "windows":
            command = (
                "node",
                "extension/scripts/run-installed-vsix-smoke.js",
                "--engine-root",
                str(tmp_path),
                "--vsix",
                str(artifact),
                "--expected-sha256",
                artifact_binding["sha256"],
                "--receipt",
                str(receipt),
                "--lifecycle-receipt",
                str(lifecycle),
            )
        else:
            root_wsl = f"/mnt/{tmp_path.drive[0].lower()}/{tmp_path.as_posix()[3:]}"
            artifact_wsl = f"{root_wsl}/candidate.vsix"
            receipt_wsl = f"{root_wsl}/{receipt.name}"
            lifecycle_wsl = f"{root_wsl}/{lifecycle.name}"
            command = (
                "wsl.exe",
                "-d",
                "Ubuntu",
                "--",
                "bash",
                "-lc",
                " ".join(
                    (
                        "node extension/scripts/run-installed-vsix-smoke.js",
                        f"--engine-root {shlex.quote(root_wsl)}",
                        f"--vsix {shlex.quote(artifact_wsl)}",
                        f"--expected-sha256 {shlex.quote(artifact_binding['sha256'])}",
                        f"--receipt {shlex.quote(receipt_wsl)}",
                        f"--lifecycle-receipt {shlex.quote(lifecycle_wsl)}",
                    )
                ),
            )
        return MemberPaths(
            command=command,
            log=tmp_path / f"{name}.log",
            receipt=receipt,
            lifecycle=lifecycle,
            report=tmp_path / f"{name}.report.json" if exhaustive else None,
        )

    return Config(
        root=tmp_path,
        candidate_id=candidate,
        artifact=artifact,
        artifact_sha256=artifact_binding["sha256"],
        artifact_size=observed.st_size,
        artifact_mtime_ns=observed.st_mtime_ns,
        summary_output=tmp_path / "summary.json",
        package_receipt=tmp_path / "package.json",
        install_receipt=tmp_path / "install.json",
        smoke_timeout_seconds=600,
        exhaustive_timeout_seconds=4200,
        windows=member("windows"),
        ubuntu=member("ubuntu"),
        exhaustive=member("exhaustive", exhaustive=True),
    )


class _FakeProcess:
    def __init__(self, owner: "FakeEffects", member: str, exit_code: int):
        self.owner = owner
        self.member = member
        self.exit_code = exit_code

    def wait(self) -> int:
        self.owner.events.append(f"wait:{self.member}")
        return self.exit_code


class FakeEffects:
    def __init__(
        self,
        *,
        failures: set[str] | None = None,
        launch_failures: set[str] | None = None,
    ):
        self.failures = failures or set()
        self.launch_failures = launch_failures or set()
        self.events: list[str] = []

    def claim(self, config: Config) -> dict[str, str]:
        self.events.append("claim")
        return {
            "claim_id": (
                f"release-stage:{config.candidate_id}:installed_operational:one"
            )
        }

    def finish(self, config: Config, claim_id: str, passed: bool) -> None:
        self.events.append(f"finish:{str(passed).lower()}")

    def advance(self, config: Config) -> None:
        self.events.append("advance")

    def start(
        self, config: Config, member: str, paths: MemberPaths
    ) -> _FakeProcess:
        self.events.append(f"start:{member}")
        if member in self.launch_failures:
            raise RuntimeError(f"launch failed: {member}")
        paths.log.write_text(member, encoding="utf-8")
        artifact = {
            "path": config.relative(config.artifact),
            "sha256": config.artifact_sha256,
            "size": config.artifact_size,
        }
        if member == "exhaustive-installed-exact-vsix-host-walk":
            _write(
                paths.receipt,
                {
                    "schema_version": "px.operational-ui-walk/1.2",
                    "campaign_id": config.candidate_id,
                    "artifact": artifact,
                    "hostErrors": [],
                    "profileFailures": [],
                },
            )
            _write(
                paths.report,
                {
                    "schema_version": "px.isolated-current-source-operational-walk/1.1",
                    "status_truth": {
                        "terminal_state": "completed",
                        "operationally_complete": True,
                        "summary": {"issue_count": 0, "blocking_issue_count": 0},
                    },
                    "child_lifecycle": {
                        "operational_status": {"scope_complete": True},
                        "installed_artifact": {
                            "path": config.artifact.name,
                            "sha256": config.artifact_sha256,
                            "unchanged_after_install": True,
                        },
                    },
                    "owner_lifecycle": {"process_tree_closed_verified": True},
                    "cleanup": {"reclaimed": True},
                },
            )
        else:
            platform = "windows" if member.startswith("windows") else "ubuntu"
            lifecycle = {
                "schema_version": "px.owned-host-run/1.0",
                "status": "completed",
                "worker_exit_verified": True,
                "exit_code": 0,
                "residual_owned_pids_after": [],
                "process_tree_closed_verified": True,
            }
            _write(
                paths.receipt,
                {
                    "schema_version": "px.installed-vsix-certification/1.1",
                    "platform": "win32" if platform == "windows" else "linux",
                    "artifact": {
                        "name": config.artifact.name,
                        "sha256_before": config.artifact_sha256,
                        "sha256_after": config.artifact_sha256,
                        "unchanged": True,
                    },
                    "engine_connected": True,
                    "engine_identity": {
                        "manifest_path": "registry/engine_identity.json",
                        "manifest_sha256": hashlib.sha256(
                            (config.root / "registry/engine_identity.json").read_bytes()
                        ).hexdigest(),
                        "tree_sha256": "4" * 64,
                        "file_total": 1,
                    },
                    "process_lifecycle": lifecycle,
                    "host": {"schema_version": "px.vscode-host-listener-smoke/1.0"},
                },
            )
            _write(paths.lifecycle, lifecycle)
        return _FakeProcess(self, member, 1 if member in self.failures else 0)


def test_plan_has_no_release_or_process_effect(tmp_path: Path) -> None:
    config = _config(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    result = plan(config)
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert result["effects"] is False
    assert result["retries"] == 0
    assert before == after
    assert not config.summary_output.exists()


@pytest.mark.parametrize(
    ("receipt_name", "field", "value", "message"),
    [
        ("package.json", "status", "failed", "package receipt contradicts"),
        ("package.json", "attempt_count", 2, "package receipt contradicts"),
        ("install.json", "audit_valid", False, "install receipt contradicts"),
        ("install.json", "release_stage", "failed", "install receipt contradicts"),
        ("install.json", "tree_digest_after", "6" * 64, "install receipt denominator"),
    ],
)
def test_preclaim_rejects_contradictory_stage_receipts(
    tmp_path: Path,
    receipt_name: str,
    field: str,
    value: object,
    message: str,
) -> None:
    config = _config(tmp_path)
    path = tmp_path / receipt_name
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt[field] = value
    _write(path, receipt)
    effects = FakeEffects()
    with pytest.raises(OwnerBlocked, match=message):
        execute(config, effects)
    assert effects.events == []


def test_smokes_are_concurrent_and_exhaustive_is_windows_serialized(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    effects = FakeEffects()
    summary = execute(config, effects)
    assert summary["schema_version"] == "px.installed-operational-run-summary/1.1"
    assert summary["all_passed"] is True
    assert summary["retries"] == 0
    assert effects.events == [
        "claim",
        "start:windows-exact-vsix-smoke",
        "start:ubuntu-exact-vsix-smoke",
        "wait:windows-exact-vsix-smoke",
        "wait:ubuntu-exact-vsix-smoke",
        "start:exhaustive-installed-exact-vsix-host-walk",
        "wait:exhaustive-installed-exact-vsix-host-walk",
        "finish:true",
        "advance",
    ]
    assert {member["member"] for member in summary["members"]} == {
        "windows-exact-vsix-smoke",
        "ubuntu-exact-vsix-smoke",
        "exhaustive-installed-exact-vsix-host-walk",
    }


def test_smoke_failure_still_collects_exhaustive_and_never_retries(tmp_path: Path) -> None:
    config = _config(tmp_path)
    effects = FakeEffects(failures={"windows-exact-vsix-smoke"})
    with pytest.raises(OwnerBlocked, match="denominator failed"):
        execute(config, effects)
    assert effects.events.count("start:windows-exact-vsix-smoke") == 1
    assert effects.events.count("start:ubuntu-exact-vsix-smoke") == 1
    assert effects.events.count("start:exhaustive-installed-exact-vsix-host-walk") == 1
    assert effects.events.count("wait:exhaustive-installed-exact-vsix-host-walk") == 1
    assert effects.events[-1] == "finish:false"
    assert "advance" not in effects.events
    summary = json.loads(config.summary_output.read_text(encoding="utf-8"))
    assert summary["all_passed"] is False
    assert summary["retries"] == 0


def test_missing_failed_smoke_receipt_still_collects_exhaustive(tmp_path: Path) -> None:
    config = _config(tmp_path)

    class MissingReceiptEffects(FakeEffects):
        def start(
            self, config: Config, member: str, paths: MemberPaths
        ) -> _FakeProcess:
            process = super().start(config, member, paths)
            if member == "windows-exact-vsix-smoke":
                paths.receipt.unlink()
                paths.lifecycle.unlink()
                process.exit_code = 1
            return process

    effects = MissingReceiptEffects()
    with pytest.raises(OwnerBlocked, match="denominator failed"):
        execute(config, effects)
    summary = json.loads(config.summary_output.read_text(encoding="utf-8"))
    assert len(summary["members"]) == 3
    assert summary["members"][0]["valid"] is False
    assert summary["members"][2]["valid"] is True


def test_second_smoke_launch_failure_still_waits_first_process(tmp_path: Path) -> None:
    config = _config(tmp_path)
    effects = FakeEffects(launch_failures={"ubuntu-exact-vsix-smoke"})
    with pytest.raises(OwnerBlocked, match="launch failed"):
        execute(config, effects)
    assert effects.events[:4] == [
        "claim",
        "start:windows-exact-vsix-smoke",
        "start:ubuntu-exact-vsix-smoke",
        "wait:windows-exact-vsix-smoke",
    ]
    assert effects.events[-1] == "finish:false"
    assert not any("exhaustive" in event for event in effects.events)


def test_package_install_receipts_must_use_bound_object_schema(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    package = json.loads(config.package_receipt.read_text(encoding="utf-8"))
    package["artifact"] = config.relative(config.artifact)
    _write(config.package_receipt.with_suffix(".replacement"), package)
    config.package_receipt.write_text(json.dumps(package), encoding="utf-8")
    effects = FakeEffects()
    with pytest.raises(OwnerBlocked, match="object-schema identity-bound"):
        execute(config, effects)
    assert effects.events == []
    assert not config.summary_output.exists()


def test_installed_owner_reads_selected_campaign_and_preserves_legacy(tmp_path,monkeypatch):
    from scripts.run_installed_operational_owner import ProductionEffects, _identity
    from runtime import project_revision_succession
    config=_config(tmp_path)
    legacy=tmp_path/".agentic_engineering_os_px/processing-order/repair-campaign.json"
    selected=tmp_path/"revision-fixture/repair-campaign.json"
    selected.parent.mkdir();selected.write_bytes(legacy.read_bytes())
    legacy.write_text('{"phase":"repair","intake_open":true,"unresolved":["legacy-trap"]}')
    image=legacy.read_bytes()
    monkeypatch.setattr(project_revision_succession,"current_campaign_path",lambda root:selected)
    assert _identity(config)[0]["campaign_id"] == config.candidate_id
    ProductionEffects().advance(config)
    assert json.loads(selected.read_bytes())["phase"] == "installed_operational"
    assert legacy.read_bytes() == image
    selected.rename(selected.with_suffix(".retained"))
    with pytest.raises(FileNotFoundError):_identity(config)


def test_observed_smoke_hash_slot_requires_authenticated_mode_and_exact_digest():
    from scripts.run_installed_operational_owner import observed_member_argv, OBSERVED_SHA_SLOT
    raw=json.dumps(['node','smoke.js','--expected-sha256',OBSERVED_SHA_SLOT])
    assert observed_member_argv(raw,sha256='a'*64,observed=True,label='fixture')[-1]=='a'*64
    with pytest.raises(OwnerBlocked,match='authenticated'):
        observed_member_argv(raw,sha256='a'*64,observed=False,label='fixture')
    with pytest.raises(OwnerBlocked,match='digest'):
        observed_member_argv(raw,sha256='not-a-digest',observed=True,label='fixture')
    shell=json.dumps(['wsl.exe','--','bash','-lc','node smoke.js --expected-sha256 '+OBSERVED_SHA_SLOT])
    assert observed_member_argv(shell,sha256='b'*64,observed=True,label='fixture')[-1].endswith('b'*64)


def test_current_operational_owner_refuses_legacy_raw_launch_before_output(tmp_path,monkeypatch):
    from dataclasses import replace
    from scripts.run_installed_operational_owner import ProductionEffects
    config=replace(_config(tmp_path),stage_owner_config=tmp_path/'native-stage.json')
    def forbidden(*args,**kwargs):pytest.fail('no raw subprocess may launch in current operational mode')
    monkeypatch.setattr('subprocess.Popen',forbidden)
    with pytest.raises(OwnerBlocked,match='native process custody'):
        ProductionEffects().start(config,'windows',config.windows)
    assert not config.windows.log.exists()


@pytest.mark.parametrize('command',[
    ['node','smoke.js','--other','__PX_OBSERVED_VSIX_SHA256__'],
    ['node','smoke.js','prefix__PX_OBSERVED_VSIX_SHA256__'],
    ['node','smoke.js','--expected-sha256','__PX_OBSERVED_VSIX_SHA256__','__PX_OBSERVED_VSIX_SHA256__'],
    ['wsl.exe','--','bash','-lc','echo __PX_OBSERVED_VSIX_SHA256__'],
])
def test_observed_digest_cannot_expand_unrelated_arguments(command):
    from scripts.run_installed_operational_owner import observed_member_argv
    with pytest.raises(OwnerBlocked,match='slot'):
        observed_member_argv(json.dumps(command),sha256='a'*64,observed=True,label='fixture')


def test_current_operational_execution_refuses_before_claim_or_output(tmp_path,monkeypatch):
    from dataclasses import replace
    from scripts.run_installed_operational_owner import ProductionEffects
    config=replace(_config(tmp_path),stage_owner_config=tmp_path/'native-stage.json')
    def forbidden(*args,**kwargs):pytest.fail('unsupported current owner must never consume a native claim')
    monkeypatch.setattr(ProductionEffects,'claim',forbidden)
    with pytest.raises(OwnerBlocked,match='before claim'):
        execute(config)
    assert not config.summary_output.exists()


@pytest.mark.parametrize('entry',['raw_start','receipt','config','execute'])
def test_authoritative_current_campaign_cannot_downgrade_to_legacy_mode(tmp_path,monkeypatch,entry):
    from types import SimpleNamespace
    from scripts import run_installed_operational_owner as owner
    config=_config(tmp_path)
    _write(tmp_path/'policies/rev1xx-validation.json',{'schema_version':'px.validation-basis/1.0',
        'basis':'current_implementation','authority':'OWNER-FRESH-VALIDATION-001','campaign_id':'fixture-current-policy'})
    from runtime.release_campaign import release_state_relative
    legacy=tmp_path/'.agentic_engineering_os_px/processing-order/release-identity.json'
    _write(tmp_path/release_state_relative(tmp_path),json.loads(legacy.read_bytes()))
    def forbidden(*args,**kwargs):pytest.fail('a current campaign cannot enter legacy launch or claim')
    monkeypatch.setattr('subprocess.Popen',forbidden)
    monkeypatch.setattr(owner.ProductionEffects,'claim',forbidden)
    with pytest.raises((OwnerBlocked,ValueError),match='current|mode'):
        if entry=='raw_start':owner.ProductionEffects().start(config,'windows',config.windows)
        elif entry=='execute':owner.execute(config)
        elif entry=='receipt':
            release,identity=owner._identity(config)
            owner._stage_receipt(config,config.package_receipt,label='package',identity=identity,
                claim_id=release['stages']['package']['claim_id'],artifact=owner._artifact_binding(config))
        else:
            args=dict(vars(config))
            for member in ('windows','ubuntu','exhaustive'):
                paths=getattr(config,member);args[member+'_argv_json']=json.dumps(list(paths.command))
                args[member+'_log']=paths.log;args[member+'_receipt']=paths.receipt
                args[member+'_lifecycle_receipt']=paths.lifecycle
            args['exhaustive_report']=config.exhaustive.report
            owner._config(SimpleNamespace(**args))
    assert not config.windows.log.exists() and not config.summary_output.exists()
