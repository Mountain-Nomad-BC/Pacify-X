"""Build a fresh PACIFY-X release-candidate configuration pair.

This builder intentionally does *not* clone or string-rewrite a prior candidate.
Every candidate-specific path, owner command, artifact identity, installed identity,
Git tag target, and timeout is derived from the supplied build specification and
the current repository state.

The repository source is expected to have been repaired, reconciled, committed,
pushed, and converged before this script is used.  The generated control files
may exist only if release-source classification recognizes them as mutable
control state; they must never appear in ``blocking_paths``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shlex
import stat
import subprocess
import sys
from typing import Any, Mapping
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.certification_contract import STEP_ORDER  # noqa: E402

SPEC_SCHEMA = "px.release-candidate-build-spec/1.0"
AUTOMATION_SCHEMA = "px.release-candidate-automation/1.0"
STAGE_SCHEMA = "px.release-stage-owner-config/1.0"
DATE_RE = re.compile(r"^20\d{6}$")
SAFE_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_TIMEOUTS: dict[str, int] = {
    "archive_clear": 120,
    "reconcile": 900,
    "identity": 300,
    "sections": 12000,  # replaced with the current profile envelope below
    "full_profile": 14190,  # replaced with the current profile envelope below
    "validate": 1800,
    "package": 600,
    "install": 900,
    "installed_operational": 7200,
    "card_reconcile": 1800,
    "preflight": 3600,
    "finalize": 3600,
}


class BuildBlocked(RuntimeError):
    """The candidate config cannot be built without stale or ambiguous state."""


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildBlocked(f"expected JSON object: {path}")
    return value


def _required(value: Mapping[str, Any], key: str) -> str:
    result = str(value.get(key) or "").strip()
    if not result or "\x00" in result:
        raise BuildBlocked(f"build spec field {key} is required")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise BuildBlocked(
            f"git {' '.join(args)} failed" + (f": {detail}" if detail else "")
        )
    return result.stdout.strip()


def _relative(root: Path, path: Path, label: str) -> str:
    target = path.resolve()
    try:
        return target.relative_to(root).as_posix()
    except ValueError as exc:
        raise BuildBlocked(f"{label} must remain inside repository: {target}") from exc


def _resolve_inside(root: Path, raw: object, label: str) -> Path:
    source = Path(str(raw or ""))
    if not str(source) or ".." in source.parts:
        raise BuildBlocked(f"unsafe {label} path")
    target = (source if source.is_absolute() else root / source).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise BuildBlocked(f"{label} escapes repository: {target}") from exc
    return target


def _write_new(path: Path, value: object) -> None:
    if path.exists():
        raise BuildBlocked(f"refusing to overwrite candidate control file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _zip_counts(path: Path) -> tuple[int, int]:
    with zipfile.ZipFile(path) as archive:
        rows = archive.infolist()
        names = [row.filename for row in rows]
        if len(names) != len(set(names)):
            raise BuildBlocked("VSIX contains duplicate ZIP entry names")
        if archive.testzip() is not None:
            raise BuildBlocked("VSIX CRC validation failed")
        try:
            archive.getinfo("extension.vsixmanifest")
        except KeyError as exc:
            raise BuildBlocked("VSIX is missing extension.vsixmanifest") from exc
        install_entries = {
            row.filename.removeprefix("extension/")
            for row in rows
            if not row.is_dir() and row.filename.startswith("extension/")
        }
        install_entries.add(".vsixmanifest")
    return len(rows), len(install_entries)


def _installed_tree(root: Path) -> tuple[int, list[str], str]:
    if not root.is_dir():
        raise BuildBlocked(f"installed extension directory is unavailable: {root}")
    files: dict[str, Path] = {}
    links: list[str] = []
    for current, directories, names in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        retained: list[str] = []
        for name in sorted(directories):
            path = base / name
            flags = int(getattr(path.lstat(), "st_file_attributes", 0))
            if path.is_symlink() or flags & int(
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                links.append(path.relative_to(root).as_posix() + "/")
            else:
                retained.append(name)
        directories[:] = retained
        for name in sorted(names):
            path = base / name
            relative = path.relative_to(root).as_posix()
            flags = int(getattr(path.lstat(), "st_file_attributes", 0))
            if path.is_symlink() or flags & int(
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                links.append(relative)
            elif path.is_file():
                files[relative] = path
    digest = hashlib.sha256()
    for relative in sorted(files):
        payload = files[relative].read_bytes()
        for part in (
            relative.encode(),
            b"\0",
            str(len(payload)).encode(),
            b"\0",
            hashlib.sha256(payload).digest(),
        ):
            digest.update(part)
    return len(files), sorted(links), digest.hexdigest()


def _installed_version(installed_dir: Path) -> str:
    package = installed_dir / "package.json"
    value = _object(package)
    version = str(value.get("version") or "").strip()
    if not version:
        raise BuildBlocked("installed package.json has no version")
    return version


def _windows_to_wsl(path: Path) -> str:
    # The production target is Windows.  Keep a deterministic conversion rather
    # than invoking wslpath, which could inherit profile/environment behavior.
    raw = str(path.resolve())
    win = PureWindowsPath(raw)
    if win.drive and re.fullmatch(r"[A-Za-z]:", win.drive):
        drive = win.drive[0].lower()
        tail = "/".join(win.parts[1:])
        return f"/mnt/{drive}/{tail}"
    # Useful for fixture/static validation on POSIX, not a production WSL path.
    return path.resolve().as_posix()


def _command_path(raw: object, *, label: str) -> str:
    result = str(raw or "").strip()
    if not result or "\x00" in result:
        raise BuildBlocked(f"{label} is required")
    return result


def _timeout_map(root: Path, overrides: object) -> dict[str, int]:
    try:
        from runtime.test_profiles import (  # type: ignore
            governed_full_profile_timeout_envelope,
            governed_section_timeout_envelope,
        )
    except ImportError as exc:
        raise BuildBlocked(
            "runtime.test_profiles is required to derive governed timeout envelopes"
        ) from exc

    result = dict(DEFAULT_TIMEOUTS)
    result["sections"] = int(
        governed_section_timeout_envelope(root)["__sequential_stage__"]
    )
    result["full_profile"] = int(
        governed_full_profile_timeout_envelope(root)["__sequential_stage__"]
    )
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise BuildBlocked("timeouts_seconds must be an object when supplied")
        unknown = sorted(set(overrides) - set(STEP_ORDER))
        if unknown:
            raise BuildBlocked(f"unknown timeout override(s): {', '.join(unknown)}")
        for step, value in overrides.items():
            result[str(step)] = int(value)
    if set(result) != set(STEP_ORDER):
        raise BuildBlocked("timeout map does not match canonical STEP_ORDER")
    if any(value <= 0 or value > 14400 for value in result.values()):
        raise BuildBlocked("all certification timeouts must be within 1..14400 seconds")
    section_floor = int(
        governed_section_timeout_envelope(root)["__sequential_stage__"]
    )
    profile_floor = int(
        governed_full_profile_timeout_envelope(root)["__sequential_stage__"]
    )
    if result["sections"] < section_floor:
        raise BuildBlocked("sections timeout is below the governed sequential envelope")
    if result["full_profile"] < profile_floor:
        raise BuildBlocked("full_profile timeout is below the governed sequential envelope")
    return {step: result[step] for step in STEP_ORDER}


def _validate_frozen_source(root: Path) -> tuple[str, str, str]:
    if _git(root, "diff", "--cached", "--name-only"):
        raise BuildBlocked("Git index is not empty before candidate config creation")
    head = _git(root, "rev-parse", "HEAD")
    upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    upstream_head = _git(root, "rev-parse", "@{u}")
    if not re.fullmatch(r"[0-9a-f]{40}", head) or head != upstream_head:
        raise BuildBlocked(
            f"pre-cert HEAD is not converged with {upstream}: {head} != {upstream_head}"
        )
    try:
        from runtime.release_identity import _release_dirty_state  # type: ignore
    except ImportError as exc:
        raise BuildBlocked("runtime.release_identity is required for source classification") from exc
    dirty = _release_dirty_state(root)
    classifier_errors = list(dirty.get("classifier_errors", ()))
    blocking = sorted(set(dirty.get("blocking_paths", ())), key=str.casefold)
    if classifier_errors:
        raise BuildBlocked(
            "release source classification is invalid: " + "; ".join(classifier_errors[:8])
        )
    if blocking:
        raise BuildBlocked(
            "pre-cert source is not frozen; blocking path(s): " + ", ".join(blocking[:16])
        )
    return head, upstream, upstream_head


def _release_version(root: Path, expected: object) -> str:
    try:
        from runtime.release_identity import authoritative_version  # type: ignore
    except ImportError as exc:
        raise BuildBlocked("runtime.release_identity is required") from exc
    observed = str(authoritative_version(root)).strip()
    if not observed:
        raise BuildBlocked("authoritative release version is empty")
    if expected is not None and str(expected).strip() != observed:
        raise BuildBlocked(
            f"build spec release_version differs from authoritative version: "
            f"{expected!r} != {observed!r}"
        )
    return observed


def build(spec_path: Path, automation_output: Path, stage_output: Path) -> dict[str, Any]:
    spec = _object(spec_path)
    if spec.get("schema_version") != SPEC_SCHEMA:
        raise BuildBlocked(f"build spec must use {SPEC_SCHEMA}")

    root = Path(_required(spec, "root")).resolve()
    if not root.is_dir():
        raise BuildBlocked(f"repository root is unavailable: {root}")
    automation_output = automation_output.resolve()
    stage_output = stage_output.resolve()
    automation_relative = _relative(root, automation_output, "automation output")
    stage_relative = _relative(root, stage_output, "stage output")

    candidate_id = _required(spec, "candidate_id")
    candidate_date = _required(spec, "candidate_date")
    predecessor_id = _required(spec, "predecessor_campaign_id")
    repair_campaign_id = _required(spec, "repair_campaign_id")
    prefix = _required(spec, "evidence_prefix")
    if not DATE_RE.fullmatch(candidate_date) or candidate_date not in candidate_id:
        raise BuildBlocked("candidate_date must be YYYYMMDD and occur in candidate_id")
    if candidate_id == predecessor_id:
        raise BuildBlocked("candidate and predecessor IDs must differ")
    if not SAFE_PREFIX_RE.fullmatch(prefix):
        raise BuildBlocked("evidence_prefix is not path-safe")

    head, upstream, upstream_head = _validate_frozen_source(root)
    release_version = _release_version(root, spec.get("release_version"))
    release_tag = f"v{release_version}"
    prior_tag_target = _git(root, "rev-list", "-n", "1", release_tag)
    if not re.fullmatch(r"[0-9a-f]{40}", prior_tag_target):
        raise BuildBlocked(f"annotated release tag target is unavailable: {release_tag}")

    artifact = _resolve_inside(root, _required(spec, "artifact"), "artifact")
    if not artifact.is_file():
        raise BuildBlocked(f"release artifact is unavailable: {artifact}")
    artifact_stat = artifact.stat()
    artifact_sha256 = _sha256(artifact)
    artifact_zip_count, installable_count = _zip_counts(artifact)

    installed = spec.get("install")
    if not isinstance(installed, dict):
        raise BuildBlocked("build spec install must be an object")
    installed_dir = Path(_required(installed, "directory")).resolve()
    code_command = Path(_required(installed, "code_command")).resolve()
    if not code_command.is_file():
        raise BuildBlocked(f"VS Code command is unavailable: {code_command}")
    installed_file_count, installed_links, installed_digest = _installed_tree(installed_dir)
    if installed_links:
        raise BuildBlocked(
            "installed extension contains symlink/reparse entries: "
            + ", ".join(installed_links[:16])
        )
    installed_version = _installed_version(installed_dir)
    if installed_file_count != installable_count:
        raise BuildBlocked(
            "installed file denominator differs from VSIX installable denominator: "
            f"{installed_file_count} != {installable_count}"
        )

    python_command = _command_path(spec.get("python_command") or sys.executable, label="python_command")
    node_command = _command_path(spec.get("node_command") or "node", label="node_command")
    smoke_timeout = int(spec.get("smoke_timeout_seconds") or 600)
    exhaustive_timeout = int(spec.get("exhaustive_timeout_seconds") or 4200)
    if smoke_timeout <= 0 or exhaustive_timeout <= 0:
        raise BuildBlocked("installed-operational member timeouts must be positive")
    timeouts = _timeout_map(root, spec.get("timeouts_seconds"))
    if timeouts["installed_operational"] < max(smoke_timeout, exhaustive_timeout):
        raise BuildBlocked(
            "installed_operational owner timeout must not be below a member timeout"
        )

    cohesion_dag = _resolve_inside(root, _required(spec, "cohesion_dag"), "cohesion_dag")
    if not cohesion_dag.is_file():
        raise BuildBlocked(f"cohesion DAG is unavailable: {cohesion_dag}")

    finalize = spec.get("finalize")
    if not isinstance(finalize, dict):
        raise BuildBlocked("build spec finalize must be an object")
    wheelhouse = _command_path(finalize.get("wheelhouse"), label="finalize.wheelhouse")
    artifact_dir = _command_path(finalize.get("artifact_dir"), label="finalize.artifact_dir")
    signing_key = _command_path(finalize.get("signing_key"), label="finalize.signing_key")

    # Candidate-controlled paths.  They intentionally use a fresh prefix and are
    # not copied from a predecessor candidate.
    automation_state = f"evidence/release/{prefix}-automation-state.json"
    log_root = f"evidence/release/{prefix}-driver-logs"
    installed_root = f"evidence/release/{prefix}-installed"
    installed_summary = f"evidence/release/{prefix}-installed-operational-summary.json"
    stage_logs = f"evidence/release/{prefix}-stage-owner-logs"
    stage_receipts = f"evidence/release/{prefix}-stage-receipts"
    identity_manifest = f".engineering-bootstrap/processing-order/{prefix}-source-manifest.json"
    exhaustive_output = f"{installed_root}/exhaustive-output"
    exhaustive_receipt = f"{exhaustive_output}/receipt.json"
    exhaustive_report = f"{installed_root}/exhaustive-report.json"
    windows_receipt = f"{installed_root}/windows-smoke.json"
    windows_lifecycle = f"{installed_root}/windows-lifecycle.json"
    ubuntu_receipt = f"{installed_root}/ubuntu-smoke.json"
    ubuntu_lifecycle = f"{installed_root}/ubuntu-lifecycle.json"
    package_receipt = f"{stage_receipts}/{candidate_id}-package.json"
    install_receipt = f"{stage_receipts}/{candidate_id}-install.json"
    artifact_rel = _relative(root, artifact, "artifact")

    root_wsl = _windows_to_wsl(root)
    artifact_wsl = _windows_to_wsl(artifact)
    ubuntu_receipt_wsl = _windows_to_wsl(root / ubuntu_receipt)
    ubuntu_lifecycle_wsl = _windows_to_wsl(root / ubuntu_lifecycle)
    ubuntu_distro = str(spec.get("ubuntu_distro") or "Ubuntu").strip()
    ubuntu_tmpdir = str(spec.get("ubuntu_tmpdir") or "/home/ben").strip()
    if not ubuntu_distro or not ubuntu_tmpdir:
        raise BuildBlocked("ubuntu_distro and ubuntu_tmpdir must be nonempty")

    windows_argv = [
        node_command,
        "extension/scripts/run-installed-vsix-smoke.js",
        "--engine-root",
        ".",
        "--vsix",
        artifact_rel,
        "--expected-sha256",
        artifact_sha256,
        "--receipt",
        windows_receipt,
        "--lifecycle-receipt",
        windows_lifecycle,
    ]
    ubuntu_script = " ".join(
        [
            "cd",
            shlex.quote(root_wsl),
            "&&",
            f"TMPDIR={shlex.quote(ubuntu_tmpdir)}",
            shlex.quote(node_command),
            "extension/scripts/run-installed-vsix-smoke.js",
            "--engine-root",
            shlex.quote(root_wsl),
            "--vsix",
            shlex.quote(artifact_wsl),
            "--expected-sha256",
            shlex.quote(artifact_sha256),
            "--receipt",
            shlex.quote(ubuntu_receipt_wsl),
            "--lifecycle-receipt",
            shlex.quote(ubuntu_lifecycle_wsl),
        ]
    )
    ubuntu_argv = [
        "wsl.exe",
        "-d",
        ubuntu_distro,
        "--",
        "bash",
        "-lc",
        ubuntu_script,
    ]
    exhaustive_argv = [
        node_command,
        "extension/scripts/run-isolated-current-source-walk.js",
        "--post-audit-long-running",
        "--vsix",
        artifact_rel,
        "--output",
        exhaustive_output,
        "--report",
        exhaustive_report,
    ]

    def stage_owner(step: str) -> list[str]:
        return [
            python_command,
            "-B",
            "scripts/run_release_stage_owner.py",
            "--config",
            stage_relative,
            "--step",
            step,
            "--execute",
        ]

    owners: dict[str, dict[str, list[list[str]]]] = {
        step: {"commands": [stage_owner(step)]}
        for step in STEP_ORDER[:8]
    }
    owners["installed_operational"] = {
        "commands": [[
            python_command,
            "-B",
            "scripts/run_installed_operational_owner.py",
            "--root",
            ".",
            "--candidate-id",
            candidate_id,
            "--artifact",
            artifact_rel,
            "--artifact-sha256",
            artifact_sha256,
            "--artifact-size",
            str(artifact_stat.st_size),
            "--artifact-mtime-ns",
            str(artifact_stat.st_mtime_ns),
            "--smoke-timeout-seconds",
            str(smoke_timeout),
            "--exhaustive-timeout-seconds",
            str(exhaustive_timeout),
            "--summary-output",
            installed_summary,
            "--package-receipt",
            package_receipt,
            "--install-receipt",
            install_receipt,
            "--windows-argv-json",
            json.dumps(windows_argv, separators=(",", ":")),
            "--windows-log",
            f"{installed_root}/windows.log",
            "--windows-receipt",
            windows_receipt,
            "--windows-lifecycle-receipt",
            windows_lifecycle,
            "--ubuntu-argv-json",
            json.dumps(ubuntu_argv, separators=(",", ":")),
            "--ubuntu-log",
            f"{installed_root}/ubuntu.log",
            "--ubuntu-receipt",
            ubuntu_receipt,
            "--ubuntu-lifecycle-receipt",
            ubuntu_lifecycle,
            "--exhaustive-argv-json",
            json.dumps(exhaustive_argv, separators=(",", ":")),
            "--exhaustive-log",
            f"{installed_root}/exhaustive.log",
            "--exhaustive-report",
            exhaustive_report,
            "--exhaustive-receipt",
            exhaustive_receipt,
            "--execute",
        ]]
    }
    owners["card_reconcile"] = {
        "commands": [
            [
                python_command,
                "-B",
                "scripts/reconcile_unverified_operational_controls.py",
                "--root",
                ".",
                "--check",
                "--walk-receipt",
                exhaustive_receipt,
                "--reconcile-cards",
            ],
            [
                python_command,
                "-B",
                "scripts/reconcile_cohesion_cards.py",
                "--root",
                ".",
                "--target",
                "closed",
                "--installed-proof",
                installed_summary,
                "--automation-state",
                automation_state,
            ],
            [
                python_command,
                "-B",
                "scripts/reconcile_unverified_operational_controls.py",
                "--root",
                ".",
                "--walk-receipt",
                exhaustive_receipt,
                "--reconcile-cards",
            ],
            [
                python_command,
                "-B",
                "scripts/reconcile_cohesion_cards.py",
                "--root",
                ".",
                "--target",
                "closed",
                "--installed-proof",
                installed_summary,
                "--automation-state",
                automation_state,
                "--apply",
            ],
        ]
    }
    owners["preflight"] = {
        "commands": [[
            python_command,
            "-B",
            "-m",
            "runtime.cli",
            "--root",
            ".",
            "release",
            "preflight",
            "--release",
            release_version,
            "--artifact",
            artifact_rel,
            "--deep",
        ]]
    }
    owners["finalize"] = {
        "commands": [[
            python_command,
            "-B",
            "-m",
            "runtime.cli",
            "--root",
            ".",
            "release",
            "finalize",
            "--release",
            release_version,
            "--wheelhouse",
            wheelhouse,
            "--artifact-dir",
            artifact_dir,
            "--signing-key",
            signing_key,
        ]]
    }
    if tuple(owners) != STEP_ORDER:
        raise BuildBlocked("builder owner insertion order diverges from canonical STEP_ORDER")

    automation = {
        "schema_version": AUTOMATION_SCHEMA,
        "root": os.path.relpath(root, automation_output.parent).replace("\\", "/"),
        "candidate_id": candidate_id,
        "candidate_date": candidate_date,
        "predecessor_campaign_id": predecessor_id,
        "repair_campaign_id": repair_campaign_id,
        "evidence_prefix": prefix,
        "artifact": artifact_rel,
        "artifact_sha256": artifact_sha256,
        "artifact_size": artifact_stat.st_size,
        "artifact_mtime_ns": artifact_stat.st_mtime_ns,
        "automation_state": automation_state,
        "log_root": log_root,
        "installed_summary": installed_summary,
        "installed_exhaustive_receipt": exhaustive_receipt,
        "cohesion_dag": _relative(root, cohesion_dag, "cohesion_dag"),
        "identity_manifest": {"path": identity_manifest},
        "timeouts_seconds": timeouts,
        "fresh_paths": [
            automation_state,
            log_root,
            installed_root,
            installed_summary,
            stage_logs,
            stage_receipts,
            identity_manifest,
        ],
        "owners": owners,
    }
    stage = {
        "schema_version": STAGE_SCHEMA,
        "root": os.path.relpath(root, stage_output.parent).replace("\\", "/"),
        "candidate_id": candidate_id,
        "predecessor_id": predecessor_id,
        "artifact": {
            "path": artifact_rel,
            "sha256": artifact_sha256,
            "size": artifact_stat.st_size,
            "mtime_ns": artifact_stat.st_mtime_ns,
            "entry_count": artifact_zip_count,
        },
        "evidence_dir": stage_receipts,
        "log_dir": stage_logs,
        "identity": {
            "path_manifest": identity_manifest,
            "commit_message": f"Bind {prefix} certification identity to frozen pre-cert HEAD",
            "release_tag": release_tag,
            "prior_tag_target": prior_tag_target,
        },
        "install": {
            "directory": str(installed_dir),
            "code_command": str(code_command),
            "tree_digest": installed_digest,
            "version": installed_version,
            "entry_count": installable_count,
        },
    }

    _write_new(stage_output, stage)
    try:
        _write_new(automation_output, automation)
    except BaseException:
        # Keep pair creation transactional enough to avoid a misleading half-pair.
        try:
            stage_output.unlink()
        except OSError:
            pass
        raise

    # Parse the generated pair with the actual current loaders.  This is a schema
    # validation, not an execution or candidate consumption step.
    from scripts.run_release_candidate import Config as AutomationConfig  # type: ignore
    from scripts.run_release_stage_owner import Config as StageConfig  # type: ignore

    parsed_automation = AutomationConfig.load(automation_output)
    parsed_stage = StageConfig.load(stage_output)
    if parsed_automation.candidate_id != parsed_stage.candidate_id:
        raise BuildBlocked("generated config pair has candidate mismatch")
    if parsed_automation.predecessor_campaign_id != parsed_stage.predecessor_id:
        raise BuildBlocked("generated config pair has predecessor mismatch")
    if parsed_automation.artifact != parsed_stage.artifact:
        raise BuildBlocked("generated config pair has artifact-path mismatch")
    if parsed_automation.artifact_sha256 != parsed_stage.artifact_sha256:
        raise BuildBlocked("generated config pair has artifact-SHA mismatch")
    if parsed_automation.identity_path_manifest != parsed_stage.path_manifest:
        raise BuildBlocked("generated config pair has identity-manifest mismatch")

    return {
        "schema_version": "px.release-candidate-build-result/1.0",
        "valid": True,
        "candidate_id": candidate_id,
        "automation_config": automation_relative,
        "stage_config": stage_relative,
        "frozen_git": {
            "head": head,
            "upstream": upstream,
            "upstream_head": upstream_head,
        },
        "release": {"version": release_version, "tag": release_tag, "prior_tag_target": prior_tag_target},
        "artifact": {
            "path": artifact_rel,
            "sha256": artifact_sha256,
            "size": artifact_stat.st_size,
            "mtime_ns": artifact_stat.st_mtime_ns,
            "entry_count": artifact_zip_count,
            "installable_entry_count": installable_count,
        },
        "installed": {
            "directory": str(installed_dir),
            "version": installed_version,
            "file_count": installed_file_count,
            "tree_digest": installed_digest,
        },
        "timeouts_seconds": timeouts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--automation-output", type=Path, required=True)
    parser.add_argument("--stage-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.spec.resolve(), args.automation_output, args.stage_output)
    except (BuildBlocked, OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "px.release-candidate-build-result/1.0",
                    "valid": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                indent=2,
            )
        )
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
