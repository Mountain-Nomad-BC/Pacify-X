"""Run the one-shot final-candidate installed-operational denominator."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any, Mapping, Protocol, Sequence
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUMMARY_SCHEMA = "px.installed-operational-run-summary/1.1"
SMOKE_SCHEMA = "px.installed-vsix-certification/1.1"
LIFECYCLE_SCHEMA = "px.owned-host-run/1.0"
EXHAUSTIVE_RECEIPT_SCHEMA = "px.operational-ui-walk/1.2"
EXHAUSTIVE_REPORT_SCHEMA = "px.isolated-current-source-operational-walk/1.1"
MEMBERS = (
    "windows-exact-vsix-smoke",
    "ubuntu-exact-vsix-smoke",
    "exhaustive-installed-exact-vsix-host-walk",
)


class OwnerBlocked(RuntimeError):
    """The one-shot owner cannot safely continue."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OwnerBlocked(f"expected JSON object: {path}")
    return value


def _inside(root: Path, raw: str | Path, label: str) -> Path:
    source = Path(raw)
    if not str(source) or ".." in source.parts:
        raise OwnerBlocked(f"unsafe {label} path")
    path = (source if source.is_absolute() else root / source).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OwnerBlocked(f"{label} escapes repository") from exc
    return path


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise OwnerBlocked(f"fresh output already exists: {path}")
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.new")
    try:
        with prepared.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(prepared, path)
    finally:
        if prepared.exists():
            prepared.unlink()


def _ref(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _derived_count(value: object, key: str) -> int:
    wanted = "".join(character for character in key.lower() if character.isalnum())
    found: list[object] = []

    def visit(node: object) -> None:
        if isinstance(node, dict):
            for name, child in node.items():
                if "".join(c for c in str(name).lower() if c.isalnum()) == wanted:
                    found.append(child)
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    if not found:
        raise OwnerBlocked(f"exhaustive receipt omits {key}")
    counts = [len(item) if isinstance(item, list) else int(item) for item in found]
    if len(set(counts)) != 1:
        raise OwnerBlocked(f"exhaustive receipt has conflicting {key} values")
    return counts[0]


@dataclass(frozen=True)
class MemberPaths:
    command: tuple[str, ...]
    log: Path
    receipt: Path
    lifecycle: Path | None = None
    report: Path | None = None


@dataclass(frozen=True)
class Config:
    root: Path
    candidate_id: str
    artifact: Path
    artifact_sha256: str
    artifact_size: int
    artifact_mtime_ns: int
    summary_output: Path
    package_receipt: Path
    install_receipt: Path
    smoke_timeout_seconds: int
    exhaustive_timeout_seconds: int
    windows: MemberPaths
    ubuntu: MemberPaths
    exhaustive: MemberPaths

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


class Running(Protocol):
    def wait(self) -> int: ...


class Effects(Protocol):
    def claim(self, config: Config) -> Mapping[str, Any]: ...
    def finish(self, config: Config, claim_id: str, passed: bool) -> None: ...
    def advance(self, config: Config) -> None: ...
    def start(self, config: Config, member: str, paths: MemberPaths) -> Running: ...


class _Process:
    def __init__(
        self,
        process: subprocess.Popen[str],
        stream: Any,
        timeout_seconds: int,
    ):
        self.process = process
        self.stream = stream
        self.timeout_seconds = timeout_seconds

    def wait(self) -> int:
        try:
            return self.process.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            if os.name == "nt":
                stopped = subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                try:
                    self.process.wait(timeout=30)
                except subprocess.TimeoutExpired as stop_error:
                    raise OwnerBlocked("owned Windows process tree did not stop") from stop_error
                if stopped.returncode != 0 and self.process.poll() is None:
                    raise OwnerBlocked("taskkill did not close the owned Windows process tree")
            else:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=10)
                if self.process.poll() is None:
                    raise OwnerBlocked("owned POSIX process group did not stop")
            raise OwnerBlocked(
                f"owned host exceeded {self.timeout_seconds} seconds"
            ) from exc
        finally:
            self.stream.close()


class ProductionEffects:
    def claim(self, config: Config) -> Mapping[str, Any]:
        from runtime.release_campaign import claim_release_stage

        return claim_release_stage(config.root, "installed_operational")

    def finish(self, config: Config, claim_id: str, passed: bool) -> None:
        from runtime.release_campaign import finish_release_stage

        finish_release_stage(
            config.root,
            stage="installed_operational",
            claim_id=claim_id,
            passed=passed,
        )

    def advance(self, config: Config) -> None:
        path = config.root / ".engineering-bootstrap/processing-order/repair-campaign.json"
        value = _object(path)
        if (
            value.get("phase") != "installed"
            or value.get("intake_open") is not False
            or value.get("unresolved") != []
        ):
            raise OwnerBlocked("repair phase cannot advance installed -> installed_operational")
        value["phase"] = "installed_operational"
        prepared = path.with_name(f".{path.name}.{uuid4().hex}.new")
        with prepared.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(prepared, path)

    def start(self, config: Config, member: str, paths: MemberPaths) -> Running:
        paths.log.parent.mkdir(parents=True, exist_ok=True)
        stream = paths.log.open("x", encoding="utf-8", newline="\n")
        try:
            process = subprocess.Popen(
                list(paths.command),
                cwd=config.root,
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                start_new_session=os.name != "nt",
            )
        except BaseException:
            stream.close()
            raise
        timeout = (
            config.exhaustive_timeout_seconds
            if member == MEMBERS[2]
            else config.smoke_timeout_seconds
        )
        return _Process(process, stream, timeout)


def _identity(config: Config) -> tuple[dict[str, Any], dict[str, Any]]:
    release = _object(
        config.root / ".engineering-bootstrap/processing-order/release-identity.json"
    )
    repair = _object(
        config.root / ".engineering-bootstrap/processing-order/repair-campaign.json"
    )
    stages = release.get("stages")
    identity = release.get("identity")
    if (
        release.get("campaign_id") != config.candidate_id
        or release.get("state") != "active"
        or release.get("apply_count") != 1
        or release.get("active_claim") is not None
        or not isinstance(identity, dict)
        or not isinstance(stages, dict)
        or stages.get("package", {}).get("status") != "passed"
        or stages.get("install", {}).get("status") != "passed"
        or stages.get("installed_operational", {}).get("status") != "pending"
        or repair.get("phase") != "installed"
        or repair.get("intake_open") is not False
        or repair.get("unresolved") != []
    ):
        raise OwnerBlocked("release/repair state is not ready for installed operational")
    for key in (
        "release_identity_sha256",
        "source_product_digest",
        "source_harness_digest",
    ):
        value = identity.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise OwnerBlocked(f"release identity omits {key}")
    return release, identity


def _artifact_binding(config: Config) -> dict[str, object]:
    if not config.artifact.is_file() or config.artifact.is_symlink():
        raise OwnerBlocked("artifact is not a regular file")
    stat = config.artifact.stat()
    observed = (_sha256(config.artifact), stat.st_size, stat.st_mtime_ns)
    expected = (config.artifact_sha256, config.artifact_size, config.artifact_mtime_ns)
    if observed != expected:
        raise OwnerBlocked("immutable artifact identity differs")
    return {
        "path": config.relative(config.artifact),
        "sha256": config.artifact_sha256,
        "size": config.artifact_size,
    }


def _engine_binding(config: Config) -> dict[str, object]:
    path = config.root / "registry/engine_identity.json"
    value = _object(path)
    if (
        value.get("schema_version") != "px.engine-identity/1.0"
        or not isinstance(value.get("tree_sha256"), str)
        or len(value["tree_sha256"]) != 64
        or not isinstance(value.get("file_total"), int)
        or value["file_total"] <= 0
    ):
        raise OwnerBlocked("current engine identity is invalid")
    return {
        "manifest_path": "registry/engine_identity.json",
        "manifest_sha256": _sha256(path),
        "tree_sha256": value["tree_sha256"],
        "file_total": value["file_total"],
    }


def _stage_receipt(
    config: Config,
    path: Path,
    *,
    label: str,
    identity: Mapping[str, Any],
    claim_id: object,
    artifact: Mapping[str, object],
) -> dict[str, Any]:
    value = _object(path)
    expected_schema = (
        "px.release-stage-evidence/1.0"
        if label == "package"
        else "px.install-audit-denominator/1.0"
    )
    actual_claim = value.get("claim_id")
    if label == "install" and actual_claim is None:
        actual_claim = value.get("install_claim_id")
    if (
        value.get("schema_version") != expected_schema
        or value.get("campaign_id") != config.candidate_id
        or value.get("valid") is not True
        or value.get("artifact") != dict(artifact)
        or actual_claim != claim_id
        or any(value.get(key) != identity.get(key) for key in identity if key in {
            "release_identity_sha256", "source_product_digest", "source_harness_digest"
        })
    ):
        raise OwnerBlocked(f"{label} receipt is not object-schema identity-bound evidence")
    if label == "package":
        exact = {
            "stage": "package",
            "status": "passed",
            "attempt_count": 1,
            "artifact_mtime_ns": config.artifact_mtime_ns,
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
        }
        if any(value.get(key) != expected for key, expected in exact.items()):
            raise OwnerBlocked("package receipt contradicts the passed exact audit")
        entry_count = value.get("entry_count")
        if (
            not isinstance(entry_count, int)
            or entry_count <= 0
            or value.get("unique_entry_count") != entry_count
        ):
            raise OwnerBlocked("package receipt entry denominator is invalid")
    else:
        exact = {
            "claim_id": claim_id,
            "install_claim_id": claim_id,
            "exact_version_count": 1,
            "normalized_package_json_entries": 1,
            "missing": [],
            "extra": [],
            "mismatches": [],
            "crc_failures": [],
            "installed_symlinks_before": [],
            "installed_symlinks_after": [],
            "installed_tree_unchanged": True,
            "machine_mutated": False,
            "install_command_executed": False,
            "release_stage": "passed",
            "processing_phase": "installed",
            "resource_count": 0,
            "active_processes": 0,
            "cleanup_failures": 0,
            "audit_valid": True,
        }
        if any(value.get(key) != expected for key, expected in exact.items()):
            raise OwnerBlocked("install receipt contradicts the passed exact audit")
        count = value.get("installable_entry_count")
        before = value.get("tree_digest_before")
        if (
            not isinstance(count, int)
            or count <= 0
            or value.get("installed_file_count") != count
            or value.get("verified_byte_identical_entries") != count - 1
            or value.get("tree_digest_after") != before
            or not _is_sha256(before)
        ):
            raise OwnerBlocked("install receipt denominator is invalid")
    return value


def _flag(command: tuple[str, ...], name: str) -> str:
    positions = [index for index, token in enumerate(command) if token == name]
    if len(positions) != 1 or positions[0] + 1 >= len(command):
        raise OwnerBlocked(f"canonical command must supply {name} exactly once")
    return command[positions[0] + 1]


def _wsl_path(path: Path) -> str:
    value = path.as_posix()
    if len(value) < 3 or value[1:3] != ":/":
        raise OwnerBlocked(f"cannot derive WSL path for {path}")
    return f"/mnt/{value[0].lower()}/{value[3:]}"


def _validate_commands(config: Config) -> None:
    windows = config.windows.command
    if (
        len(windows) < 2
        or Path(windows[0]).name.lower() not in {"node", "node.exe"}
        or Path(windows[1]).as_posix() != "extension/scripts/run-installed-vsix-smoke.js"
        or _inside(config.root, _flag(windows, "--engine-root"), "windows engine root")
        != config.root
        or _inside(config.root, _flag(windows, "--vsix"), "windows artifact")
        != config.artifact
        or _flag(windows, "--expected-sha256") != config.artifact_sha256
        or _inside(config.root, _flag(windows, "--receipt"), "windows receipt")
        != config.windows.receipt
        or _inside(
            config.root,
            _flag(windows, "--lifecycle-receipt"),
            "windows lifecycle",
        )
        != config.windows.lifecycle
    ):
        raise OwnerBlocked("Windows smoke command is not exactly config-bound")
    ubuntu = config.ubuntu.command
    if ubuntu[:6] != ("wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc") or len(ubuntu) != 7:
        raise OwnerBlocked("Ubuntu smoke command is not the canonical WSL wrapper")
    shell = ubuntu[6]
    ubuntu_markers = (
        "node extension/scripts/run-installed-vsix-smoke.js",
        f"--engine-root '{_wsl_path(config.root)}'",
        f"--vsix '{_wsl_path(config.artifact)}'",
        f"--expected-sha256 '{config.artifact_sha256}'",
        f"--receipt '{_wsl_path(config.ubuntu.receipt)}'",
        f"--lifecycle-receipt '{_wsl_path(config.ubuntu.lifecycle)}'",
    )
    if any(marker not in shell for marker in ubuntu_markers):
        raise OwnerBlocked("Ubuntu smoke command is not exactly config-bound")
    exhaustive = config.exhaustive.command
    if (
        len(exhaustive) < 2
        or Path(exhaustive[0]).name.lower() not in {"node", "node.exe"}
        or Path(exhaustive[1]).as_posix()
        != "extension/scripts/run-isolated-current-source-walk.js"
        or "--post-audit-long-running" not in exhaustive
        or _inside(config.root, _flag(exhaustive, "--vsix"), "exhaustive artifact")
        != config.artifact
        or _inside(config.root, _flag(exhaustive, "--output"), "exhaustive output")
        != config.exhaustive.receipt.parent
        or _inside(config.root, _flag(exhaustive, "--report"), "exhaustive report")
        != config.exhaustive.report
    ):
        raise OwnerBlocked("exhaustive command is not exactly config-bound")


def _failed_smoke_member(
    config: Config,
    paths: MemberPaths,
    *,
    member: str,
    exit_code: int,
    error: BaseException,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "member": member,
        "exit_code": exit_code,
        "artifact_unchanged": False,
        "process_tree_closed_verified": False,
        "valid": False,
        "error": f"{type(error).__name__}: {error}",
    }
    for key, path in (
        ("log", paths.log),
        ("receipt", paths.receipt),
        ("process_lifecycle_receipt", paths.lifecycle),
    ):
        if path is not None and path.is_file() and not path.is_symlink():
            result[key] = _ref(config.root, path)
    return result


def _smoke_member(
    config: Config,
    paths: MemberPaths,
    *,
    member: str,
    platform: str,
    exit_code: int,
    artifact: Mapping[str, object],
    engine: Mapping[str, object],
) -> dict[str, Any]:
    receipt = _object(paths.receipt)
    lifecycle = _object(paths.lifecycle) if paths.lifecycle is not None else {}
    smoke_artifact = receipt.get("artifact", {})
    host = receipt.get("host", {})
    embedded_lifecycle = receipt.get("process_lifecycle")
    expected_platform = "win32" if platform == "windows" else "linux"
    valid = (
        exit_code == 0
        and receipt.get("schema_version") == SMOKE_SCHEMA
        and receipt.get("platform") == expected_platform
        and isinstance(smoke_artifact, dict)
        and smoke_artifact.get("name") == config.artifact.name
        and smoke_artifact.get("sha256_before") == artifact.get("sha256")
        and smoke_artifact.get("sha256_after") == artifact.get("sha256")
        and smoke_artifact.get("unchanged") is True
        and receipt.get("engine_connected") is True
        and receipt.get("engine_identity") == dict(engine)
        and isinstance(host, dict)
        and host.get("schema_version") == "px.vscode-host-listener-smoke/1.0"
        and lifecycle.get("schema_version") == LIFECYCLE_SCHEMA
        and embedded_lifecycle == lifecycle
        and lifecycle.get("status") == "completed"
        and lifecycle.get("worker_exit_verified") is True
        and lifecycle.get("exit_code") == 0
        and lifecycle.get("residual_owned_pids_after") == []
        and lifecycle.get("process_tree_closed_verified") is True
    )
    return {
        "member": member,
        "exit_code": exit_code,
        "log": _ref(config.root, paths.log),
        "receipt": _ref(config.root, paths.receipt),
        "process_lifecycle_receipt": _ref(config.root, paths.lifecycle),
        "artifact_unchanged": smoke_artifact.get("unchanged") is True,
        "process_tree_closed_verified": lifecycle.get("process_tree_closed_verified") is True,
        "valid": valid,
    }


def _exhaustive_member(
    config: Config,
    paths: MemberPaths,
    *,
    exit_code: int,
    artifact: Mapping[str, object],
) -> dict[str, Any]:
    if paths.report is None:
        raise OwnerBlocked("exhaustive report path is missing")
    report = _object(paths.report)
    receipt = _object(paths.receipt)
    truth = report.get("status_truth", {})
    lifecycle = report.get("child_lifecycle", {})
    status = lifecycle.get("operational_status", {})
    owner = report.get("owner_lifecycle", {})
    cleanup = report.get("cleanup", {})
    installed = lifecycle.get("installed_artifact", {})
    host_errors = _derived_count(receipt, "host_errors")
    profile_failures = _derived_count(receipt, "profile_failures")
    member = {
        "member": MEMBERS[2],
        "exit_code": exit_code,
        "log": _ref(config.root, paths.log),
        "receipt": _ref(config.root, paths.receipt),
        "report": _ref(config.root, paths.report),
        "terminal_state": truth.get("terminal_state"),
        "scope_complete": status.get("scope_complete"),
        "operationally_complete": truth.get("operationally_complete"),
        "issue_count": truth.get("summary", {}).get("issue_count"),
        "blocking_issue_count": truth.get("summary", {}).get("blocking_issue_count"),
        "host_error_count": host_errors,
        "profile_failure_count": profile_failures,
        "process_tree_closed_verified": owner.get("process_tree_closed_verified"),
        "workspace_reclaimed": cleanup.get("reclaimed"),
        "artifact_unchanged": installed.get("unchanged_after_install"),
    }
    member["valid"] = (
        exit_code == 0
        and report.get("schema_version") == EXHAUSTIVE_REPORT_SCHEMA
        and receipt.get("schema_version") == EXHAUSTIVE_RECEIPT_SCHEMA
        and member["terminal_state"] == "completed"
        and member["scope_complete"] is True
        and member["operationally_complete"] is True
        and member["issue_count"] == 0
        and member["blocking_issue_count"] == 0
        and member["host_error_count"] == 0
        and member["profile_failure_count"] == 0
        and member["process_tree_closed_verified"] is True
        and member["workspace_reclaimed"] is True
        and member["artifact_unchanged"] is True
        and installed.get("path") == config.artifact.name
        and installed.get("sha256") == artifact.get("sha256")
    )
    return member


def plan(config: Config) -> dict[str, Any]:
    _validate_commands(config)
    return {
        "schema_version": "px.installed-operational-owner-plan/1.0",
        "mode": "plan",
        "effects": False,
        "valid": True,
        "candidate_id": config.candidate_id,
        "parallel": list(MEMBERS[:2]),
        "serialized_after_windows": MEMBERS[2],
        "retries": 0,
        "smoke_timeout_seconds": config.smoke_timeout_seconds,
        "exhaustive_timeout_seconds": config.exhaustive_timeout_seconds,
        "summary_output": config.relative(config.summary_output),
    }


def execute(config: Config, effects: Effects | None = None) -> dict[str, Any]:
    effects = effects or ProductionEffects()
    _validate_commands(config)
    release, identity = _identity(config)
    artifact = _artifact_binding(config)
    engine = _engine_binding(config)
    stages = release["stages"]
    _stage_receipt(
        config,
        config.package_receipt,
        label="package",
        identity=identity,
        claim_id=stages["package"]["claim_id"],
        artifact=artifact,
    )
    _stage_receipt(
        config,
        config.install_receipt,
        label="install",
        identity=identity,
        claim_id=stages["install"]["claim_id"],
        artifact=artifact,
    )
    for path in (
        config.summary_output,
        config.windows.log,
        config.windows.receipt,
        config.windows.lifecycle,
        config.ubuntu.log,
        config.ubuntu.receipt,
        config.ubuntu.lifecycle,
        config.exhaustive.log,
        config.exhaustive.receipt,
        config.exhaustive.report,
    ):
        if path is not None and path.exists():
            raise OwnerBlocked(f"fresh owner path already exists: {path}")

    claim = effects.claim(config)
    claim_id = str(claim.get("claim_id") or "")
    members: list[dict[str, Any]] = []
    passed = False
    error: BaseException | None = None
    try:
        if not claim_id.startswith(
            f"release-stage:{config.candidate_id}:installed_operational:"
        ):
            raise OwnerBlocked("installed operational claim is not candidate-bound")
        running: list[tuple[str, Running]] = []
        launch_error: BaseException | None = None
        try:
            running.append((MEMBERS[0], effects.start(config, MEMBERS[0], config.windows)))
            running.append((MEMBERS[1], effects.start(config, MEMBERS[1], config.ubuntu)))
        except BaseException as exc:
            launch_error = exc
        exit_codes: dict[str, int] = {}
        wait_error: BaseException | None = None
        for member_name, process in running:
            try:
                exit_codes[member_name] = process.wait()
            except BaseException as exc:
                wait_error = wait_error or exc
        if launch_error is not None:
            raise launch_error
        if wait_error is not None:
            raise wait_error
        windows_code = exit_codes[MEMBERS[0]]
        ubuntu_code = exit_codes[MEMBERS[1]]
        for paths, member_name, platform, member_code in (
            (config.windows, MEMBERS[0], "windows", windows_code),
            (config.ubuntu, MEMBERS[1], "ubuntu", ubuntu_code),
        ):
            try:
                member_result = _smoke_member(
                    config,
                    paths,
                    member=member_name,
                    platform=platform,
                    exit_code=member_code,
                    artifact=artifact,
                    engine=engine,
                )
            except (OSError, ValueError, json.JSONDecodeError, OwnerBlocked) as exc:
                member_result = _failed_smoke_member(
                    config,
                    paths,
                    member=member_name,
                    exit_code=member_code,
                    error=exc,
                )
            members.append(member_result)
        exhaustive = effects.start(config, MEMBERS[2], config.exhaustive)
        members.append(
            _exhaustive_member(
                config, config.exhaustive,
                exit_code=exhaustive.wait(), artifact=artifact,
            )
        )
        passed = len(members) == 3 and all(
            member.get("valid") is True for member in members
        )
        if passed:
            _artifact_binding(config)
    except BaseException as exc:
        error = exc

    summary = {
        "schema_version": SUMMARY_SCHEMA,
        "campaign_id": config.candidate_id,
        "claim_id": claim_id,
        "finished_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "release_identity_sha256": identity["release_identity_sha256"],
        "source_product_digest": identity["source_product_digest"],
        "source_harness_digest": identity["source_harness_digest"],
        "artifact": artifact,
        "package_receipt": _ref(config.root, config.package_receipt),
        "install_receipt": _ref(config.root, config.install_receipt),
        "all_passed": passed,
        "retries": 0,
        "cross_platform_smokes_parallel": True,
        "windows_hosts_serialized": True,
        "members": members,
    }
    if error is not None:
        summary["error"] = f"{type(error).__name__}: {error}"
    try:
        _write_json(config.summary_output, summary)
    except BaseException as exc:
        passed = False
        error = error or exc
    effects.finish(config, claim_id, passed)
    if passed:
        effects.advance(config)
    if error is not None:
        raise OwnerBlocked(str(error)) from error
    if not passed:
        raise OwnerBlocked("installed operational denominator failed")
    return summary


def _argv(value: str, label: str) -> tuple[str, ...]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not parsed or any(
        not isinstance(item, str) or not item for item in parsed
    ):
        raise OwnerBlocked(f"{label} must be a nonempty JSON string array")
    return tuple(parsed)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=Path.cwd())
    result.add_argument("--candidate-id", required=True)
    result.add_argument("--artifact", type=Path, required=True)
    result.add_argument("--artifact-sha256", required=True)
    result.add_argument("--artifact-size", type=int, required=True)
    result.add_argument("--artifact-mtime-ns", type=int, required=True)
    result.add_argument("--smoke-timeout-seconds", type=int, default=600)
    result.add_argument("--exhaustive-timeout-seconds", type=int, default=4200)
    result.add_argument("--summary-output", type=Path, required=True)
    result.add_argument("--package-receipt", type=Path, required=True)
    result.add_argument("--install-receipt", type=Path, required=True)
    for name in ("windows", "ubuntu"):
        result.add_argument(f"--{name}-argv-json", required=True)
        result.add_argument(f"--{name}-log", type=Path, required=True)
        result.add_argument(f"--{name}-receipt", type=Path, required=True)
        result.add_argument(f"--{name}-lifecycle-receipt", type=Path, required=True)
    result.add_argument("--exhaustive-argv-json", required=True)
    result.add_argument("--exhaustive-log", type=Path, required=True)
    result.add_argument("--exhaustive-report", type=Path, required=True)
    result.add_argument("--exhaustive-receipt", type=Path, required=True)
    result.add_argument("--execute", action="store_true")
    return result


def _config(args: argparse.Namespace) -> Config:
    root = args.root.resolve(strict=True)

    def path(value: Path, label: str) -> Path:
        return _inside(root, value, label)

    config = Config(
        root=root,
        candidate_id=args.candidate_id.strip(),
        artifact=path(args.artifact, "artifact"),
        artifact_sha256=args.artifact_sha256,
        artifact_size=args.artifact_size,
        artifact_mtime_ns=args.artifact_mtime_ns,
        summary_output=path(args.summary_output, "summary_output"),
        package_receipt=path(args.package_receipt, "package_receipt"),
        install_receipt=path(args.install_receipt, "install_receipt"),
        smoke_timeout_seconds=args.smoke_timeout_seconds,
        exhaustive_timeout_seconds=args.exhaustive_timeout_seconds,
        windows=MemberPaths(
            _argv(args.windows_argv_json, "windows argv"),
            path(args.windows_log, "windows log"),
            path(args.windows_receipt, "windows receipt"),
            lifecycle=path(args.windows_lifecycle_receipt, "windows lifecycle"),
        ),
        ubuntu=MemberPaths(
            _argv(args.ubuntu_argv_json, "ubuntu argv"),
            path(args.ubuntu_log, "ubuntu log"),
            path(args.ubuntu_receipt, "ubuntu receipt"),
            lifecycle=path(args.ubuntu_lifecycle_receipt, "ubuntu lifecycle"),
        ),
        exhaustive=MemberPaths(
            _argv(args.exhaustive_argv_json, "exhaustive argv"),
            path(args.exhaustive_log, "exhaustive log"),
            path(args.exhaustive_receipt, "exhaustive receipt"),
            report=path(args.exhaustive_report, "exhaustive report"),
        ),
    )
    if (
        not config.candidate_id
        or len(config.artifact_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in config.artifact_sha256.lower()
        )
        or config.artifact_size <= 0
        or config.artifact_mtime_ns <= 0
        or config.smoke_timeout_seconds <= 0
        or config.exhaustive_timeout_seconds <= 0
    ):
        raise OwnerBlocked("candidate and immutable artifact identity are required")
    return config


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        config = _config(args)
        result = execute(config) if args.execute else plan(config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OwnerBlocked, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [f"{type(exc).__name__}: {exc}"]}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
