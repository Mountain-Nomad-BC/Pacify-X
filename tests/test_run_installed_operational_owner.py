from __future__ import annotations

import hashlib
import json
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
        tmp_path / ".engineering-bootstrap/processing-order/release-identity.json",
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
        tmp_path / ".engineering-bootstrap/processing-order/repair-campaign.json",
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
                        f"--engine-root '{root_wsl}'",
                        f"--vsix '{artifact_wsl}'",
                        f"--expected-sha256 '{artifact_binding['sha256']}'",
                        f"--receipt '{receipt_wsl}'",
                        f"--lifecycle-receipt '{lifecycle_wsl}'",
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
