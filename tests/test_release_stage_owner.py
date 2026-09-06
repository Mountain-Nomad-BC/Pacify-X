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
    plan,
    run,
    resource_postcondition,
)


class FakeEffects:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.verified: list[str] = []

    def execute(self, step: str, config: Config) -> dict[str, object]:
        self.executed.append(step)
        return {"valid": True}

    def verify(self, step: str, config: Config) -> None:
        self.verified.append(step)


def fixture(tmp_path: Path, step: str) -> Config:
    artifact = tmp_path / "candidate.vsix"
    artifact.write_bytes(b"artifact")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"paths": ["one.txt", "two.txt"], "mutable_paths": []}),
        encoding="utf-8",
    )
    state_dir = tmp_path / ".engineering-bootstrap/processing-order"
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
def test_each_invocation_admits_only_selected_step(tmp_path: Path, step: str) -> None:
    config = fixture(tmp_path, step)
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
    repair = tmp_path / ".engineering-bootstrap/processing-order/repair-campaign.json"
    value = json.loads(repair.read_text(encoding="utf-8"))
    value["phase"] = "installed"
    repair.write_text(json.dumps(value), encoding="utf-8")
    assert check(config, "package")["valid"] is False


def test_archive_check_allows_one_unused_cleared_predecessor(tmp_path: Path) -> None:
    config = fixture(tmp_path, "archive_clear")
    state = tmp_path / ".engineering-bootstrap/processing-order/release-identity.json"
    state.write_text(
        json.dumps(
            {
                "campaign_id": config.predecessor_id,
                "state": "cleared",
                "apply_count": 0,
                "identity": None,
                "active_claim": None,
            }
        ),
        encoding="utf-8",
    )
    assert check(config, "archive_clear")["valid"] is True


def test_archive_check_allows_one_unused_invalid_identity_predecessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, "archive_clear")
    repair = tmp_path / ".engineering-bootstrap/processing-order/repair-campaign.json"
    repair_value = json.loads(repair.read_text(encoding="utf-8"))
    repair_value["phase"] = "revision_reconciled"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    state = tmp_path / ".engineering-bootstrap/processing-order/release-identity.json"
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
        lambda root, verify_source=False: {"valid": False, "errors": ["drift"]},
    )
    assert check(config, "archive_clear")["valid"] is True


def test_archive_effect_routes_unused_invalid_identity_to_canonical_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = fixture(tmp_path, "archive_clear")
    repair = tmp_path / ".engineering-bootstrap/processing-order/repair-campaign.json"
    repair_value = json.loads(repair.read_text(encoding="utf-8"))
    repair_value["phase"] = "revision_reconciled"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    state = tmp_path / ".engineering-bootstrap/processing-order/release-identity.json"
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
    rewinds: list[Path] = []
    monkeypatch.setattr(
        "runtime.release_campaign.rewind_invalid_release_identity_reconciliation",
        lambda root: rewinds.append(root) or {"valid": True},
    )
    receipt = ProductionEffects().execute("archive_clear", config)
    assert receipt["valid"] is True
    assert calls == [config.candidate_id]
    assert rewinds == [config.root]


def test_archive_check_allows_failed_stage_at_its_exact_repair_phase(
    tmp_path: Path,
) -> None:
    config = fixture(tmp_path, "archive_clear")
    repair = tmp_path / ".engineering-bootstrap/processing-order/repair-campaign.json"
    repair_value = json.loads(repair.read_text(encoding="utf-8"))
    repair_value["phase"] = "revision_reconciled"
    repair.write_text(json.dumps(repair_value), encoding="utf-8")
    state = tmp_path / ".engineering-bootstrap/processing-order/release-identity.json"
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
    repair = tmp_path / ".engineering-bootstrap/processing-order/repair-campaign.json"
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
    ledger = tmp_path / ".engineering-bootstrap/resource-lifecycle/ledger.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps(
            {
                "resources": [
                    {
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
    monkeypatch.setattr("scripts.run_release_stage_owner.os.getpid", lambda: 123)
    monkeypatch.setattr(
        "runtime.resource_lifecycle.resource_status",
        lambda _path: {
            "valid": True,
            "active_processes": 1,
            "reclaimable_paths": 0,
            "cleanup_failures": 0,
        },
    )
    assert resource_postcondition(config)["valid"] is True
    value = json.loads(ledger.read_text(encoding="utf-8"))
    value["resources"][0]["pid"] = 456
    ledger.write_text(json.dumps(value), encoding="utf-8")
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


def test_identity_uses_explicit_cached_set_and_one_annotated_retag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = fixture(tmp_path, "identity")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.7.0"\n', encoding="utf-8"
    )
    calls: list[tuple[str, ...]] = []

    class GitEffects(ProductionEffects):
        def git(self, config: Config, *args: str) -> str:
            calls.append(args)
            if args[:2] in {("diff", "--name-only"), ("ls-files", "--others")}:
                return "one.txt\0two.txt\0"
            if args[:3] == ("diff", "--cached", "--name-only"):
                return "one.txt\0two.txt\0"
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
                "blocking_paths": ["one.txt", "two.txt"],
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
    assert ("add", "--", "one.txt", "two.txt") in calls
    tag_call = next(call for call in calls if call[:4] == ("tag", "-f", "-a", "v0.7.0"))
    assert tag_call[4:6] == ("-m", f"v0.7.0 {config.candidate_id}")
    assert sum(call[:2] == ("commit", "-m") for call in calls) == 1


def test_identity_requires_exact_mutable_control_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = fixture(tmp_path, "identity")
    config.path_manifest.write_text(
        json.dumps(
            {
                "paths": ["one.txt", "two.txt"],
                "mutable_paths": ["registry/operational_gap_ledger.jsonl"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runtime.release_identity._release_dirty_state",
        lambda root: {
            "blocking_paths": ["one.txt", "two.txt"],
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
