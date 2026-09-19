"""Read-only structural validation for a PACIFY-X certification candidate.

The validator does not create a candidate, move a tag, claim a stage, write a
receipt, reconcile cards, or mutate release state.  It validates the candidate
configuration pair against the canonical certification contract and the current
repository/artifact state, collecting all discoverable defects in one report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.certification_contract import (  # noqa: E402
    CONTRACT_BY_STEP,
    STEP_ORDER,
    validate_contract,
)
from scripts.run_release_candidate import Config as AutomationConfig  # noqa: E402
from scripts.run_release_stage_owner import Config as StageConfig  # noqa: E402

SCHEMA = "px.certification-pipeline-validation/1.0"

REQUIRED_REPO_FILES = (
    # Direct certification control surface.
    "scripts/run_release_candidate.py",
    "scripts/run_release_stage_owner.py",
    "scripts/run_installed_operational_owner.py",
    "scripts/reconcile_unverified_operational_controls.py",
    "scripts/reconcile_cohesion_cards.py",
    "runtime/certification_contract.py",
    "runtime/release_campaign.py",
    "runtime/release_identity.py",
    # Direct command targets.
    "runtime/cli.py",
    "extension/scripts/run-installed-vsix-smoke.js",
    "extension/scripts/run-isolated-current-source-walk.js",
    # Static transitive project dependencies observed from the supplied source.
    "runtime/bounded_walk.py",
    "runtime/contracts.py",
    "runtime/dependency_audit.py",
    "runtime/effect_surface.py",
    "runtime/evidence_claims.py",
    "runtime/evidence_portability.py",
    "runtime/external_evidence.py",
    "runtime/file_lock.py",
    "runtime/generated_artifacts.py",
    "runtime/graph_registry.py",
    "runtime/input_files.py",
    "runtime/integration_registry.py",
    "runtime/json_io.py",
    "runtime/licensing.py",
    "runtime/numeric_inputs.py",
    "runtime/registry.py",
    "runtime/registry_envelope.py",
    "runtime/repository_scope.py",
    "runtime/resource_lifecycle.py",
    "runtime/resource_storage.py",
    "runtime/structural_integrity.py",
    "runtime/test_profiles.py",
    "runtime/verification_status.py",
    "runtime/wal_transaction.py",
    "scripts/clean_source_export.py",
)

class ValidationBlocked(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
        errors=None if binary else "replace",
        timeout=60,
        check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode != 0:
        stderr = result.stderr
        stdout = result.stdout
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        detail = str(stderr or stdout or "").strip()
        raise ValidationBlocked(
            f"git {' '.join(args)} failed" + (f": {detail}" if detail else "")
        )
    return result.stdout


def _status_snapshot(root: Path) -> bytes:
    value = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        binary=True,
    )
    assert isinstance(value, bytes)
    return value


def _option_map(command: Sequence[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    index = 0
    while index < len(command):
        token = command[index]
        if token.startswith("--"):
            if index + 1 < len(command) and not command[index + 1].startswith("--"):
                result.setdefault(token, []).append(command[index + 1])
                index += 2
                continue
            result.setdefault(token, []).append("")
        index += 1
    return result


def _one(options: Mapping[str, list[str]], key: str) -> str | None:
    values = options.get(key, [])
    return values[0] if len(values) == 1 else None


def _add(checks: list[dict[str, Any]], code: str, passed: bool, detail: str, **extra: Any) -> None:
    checks.append({"code": code, "passed": bool(passed), "detail": detail, **extra})


def _inside(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    path.relative_to(root)
    return path


def validate(automation_path: Path, stage_path: Path, *, allow_started: bool) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        validate_contract()
        _add(checks, "CANONICAL_CONTRACT", True, "canonical certification contract is internally consistent")
    except Exception as exc:
        _add(checks, "CANONICAL_CONTRACT", False, f"{type(exc).__name__}: {exc}")
        errors.append("CANONICAL_CONTRACT")

    try:
        automation = AutomationConfig.load(automation_path.resolve())
        _add(checks, "AUTOMATION_CONFIG_SCHEMA", True, "automation configuration loaded with current parser")
    except Exception as exc:
        _add(checks, "AUTOMATION_CONFIG_SCHEMA", False, f"{type(exc).__name__}: {exc}")
        return {"schema_version": SCHEMA, "valid": False, "errors": ["AUTOMATION_CONFIG_SCHEMA"], "checks": checks}

    try:
        stage = StageConfig.load(stage_path.resolve())
        _add(checks, "STAGE_CONFIG_SCHEMA", True, "stage-owner configuration loaded with current parser")
    except Exception as exc:
        _add(checks, "STAGE_CONFIG_SCHEMA", False, f"{type(exc).__name__}: {exc}")
        return {"schema_version": SCHEMA, "valid": False, "errors": ["STAGE_CONFIG_SCHEMA"], "checks": checks}

    root = automation.root
    before = _status_snapshot(root)

    pair_checks = {
        "CONFIG_CANDIDATE_BINDING": (automation.candidate_id == stage.candidate_id, f"{automation.candidate_id!r} == {stage.candidate_id!r}"),
        "CONFIG_PREDECESSOR_BINDING": (automation.predecessor_campaign_id == stage.predecessor_id, f"{automation.predecessor_campaign_id!r} == {stage.predecessor_id!r}"),
        "CONFIG_ARTIFACT_PATH_BINDING": (automation.artifact == stage.artifact, f"{automation.artifact} == {stage.artifact}"),
        "CONFIG_ARTIFACT_SHA_BINDING": (automation.artifact_sha256 == stage.artifact_sha256, f"{automation.artifact_sha256} == {stage.artifact_sha256}"),
        "CONFIG_ARTIFACT_SIZE_BINDING": (automation.artifact_size == stage.artifact_size, f"{automation.artifact_size} == {stage.artifact_size}"),
        "CONFIG_ARTIFACT_MTIME_BINDING": (automation.artifact_mtime_ns == stage.artifact_mtime_ns, f"{automation.artifact_mtime_ns} == {stage.artifact_mtime_ns}"),
        "CONFIG_IDENTITY_MANIFEST_BINDING": (automation.identity_path_manifest == stage.path_manifest, f"{automation.identity_path_manifest} == {stage.path_manifest}"),
    }
    for code, (passed, detail) in pair_checks.items():
        _add(checks, code, passed, detail)
        if not passed:
            errors.append(code)

    missing = [relative for relative in REQUIRED_REPO_FILES if not (root / relative).is_file()]
    _add(
        checks,
        "REQUIRED_REPO_FILES",
        not missing,
        "all certification runtime dependencies exist" if not missing else "missing: " + ", ".join(missing),
        missing=missing,
    )
    if missing:
        errors.append("REQUIRED_REPO_FILES")

    if automation.artifact.is_file():
        stat_info = automation.artifact.stat()
        observed = (_sha256(automation.artifact), stat_info.st_size, stat_info.st_mtime_ns)
        expected = (automation.artifact_sha256, automation.artifact_size, automation.artifact_mtime_ns)
        artifact_ok = observed == expected
        detail = f"observed={observed!r}; expected={expected!r}"
    else:
        artifact_ok = False
        detail = "artifact is absent"
    _add(checks, "ARTIFACT_IDENTITY", artifact_ok, detail)
    if not artifact_ok:
        errors.append("ARTIFACT_IDENTITY")

    try:
        with zipfile.ZipFile(automation.artifact) as archive:
            names = [row.filename for row in archive.infolist()]
            crc = archive.testzip()
        zip_ok = len(names) == stage.zip_entry_count and len(names) == len(set(names)) and crc is None
        detail = f"entries={len(names)} expected={stage.zip_entry_count} unique={len(set(names))} crc_failure={crc!r}"
    except Exception as exc:
        zip_ok = False
        detail = f"{type(exc).__name__}: {exc}"
    _add(checks, "ARTIFACT_ZIP_DENOMINATOR", zip_ok, detail)
    if not zip_ok:
        errors.append("ARTIFACT_ZIP_DENOMINATOR")

    fresh_existing = [automation.relative(path) for path in automation.fresh_paths if path.exists()]
    fresh_ok = allow_started or not fresh_existing
    _add(
        checks,
        "FRESH_OUTPUT_PATHS",
        fresh_ok,
        "started candidate permitted" if allow_started else ("all fresh outputs absent" if not fresh_existing else "existing: " + ", ".join(fresh_existing)),
        existing=fresh_existing,
    )
    if not fresh_ok:
        errors.append("FRESH_OUTPUT_PATHS")

    # Direct stage-owner commands must be mechanically identical for stages 1..8.
    stage_rel = stage_path.resolve().relative_to(root).as_posix()
    direct_errors: list[str] = []
    for step in STEP_ORDER[:8]:
        command = automation.owners[step][0]
        expected_tail = (
            "-B", "scripts/run_release_stage_owner.py", "--config", stage_rel,
            "--step", step, "--execute",
        )
        if len(command) < 2 or command[1:] != expected_tail:
            direct_errors.append(step)
    direct_ok = not direct_errors
    _add(checks, "DIRECT_STAGE_OWNER_COMMANDS", direct_ok, "exact" if direct_ok else "mismatch: " + ", ".join(direct_errors))
    if not direct_ok:
        errors.append("DIRECT_STAGE_OWNER_COMMANDS")

    # Installed-operational command is checked against both configuration domains.
    installed_command = automation.owners["installed_operational"][0]
    installed_opts = _option_map(installed_command)
    expected_installed = {
        "--candidate-id": automation.candidate_id,
        "--artifact": automation.relative(automation.artifact),
        "--artifact-sha256": automation.artifact_sha256,
        "--artifact-size": str(automation.artifact_size),
        "--artifact-mtime-ns": str(automation.artifact_mtime_ns),
        "--summary-output": automation.relative(automation.installed_summary),
        "--exhaustive-receipt": automation.relative(automation.installed_exhaustive_receipt),
    }
    installed_mismatches = {
        key: {"observed": _one(installed_opts, key), "expected": value}
        for key, value in expected_installed.items()
        if _one(installed_opts, key) != value
    }
    installed_ok = (
        len(installed_command) >= 3
        and installed_command[1:3] == ("-B", "scripts/run_installed_operational_owner.py")
        and not installed_mismatches
        and "--execute" in installed_opts
    )
    _add(checks, "INSTALLED_OPERATIONAL_COMMAND", installed_ok, "exact" if installed_ok else "command/config mismatch", mismatches=installed_mismatches)
    if not installed_ok:
        errors.append("INSTALLED_OPERATIONAL_COMMAND")

    # Card sequence is already strict in AutomationConfig.load. Record it as an
    # independent named check so the aggregate report is useful to humans/tools.
    _add(checks, "CARD_RECONCILE_SEQUENCE", True, "exact CHECK/CHECK/APPLY/APPLY sequence accepted by current parser")

    # Git convergence and tag binding are checked without mutating refs.
    try:
        head = str(_git(root, "rev-parse", "HEAD")).strip()
        upstream = str(_git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")).strip()
        upstream_head = str(_git(root, "rev-parse", "@{u}")).strip()
        index = str(_git(root, "diff", "--cached", "--name-only")).strip()
        git_ok = bool(re.fullmatch(r"[0-9a-f]{40}", head)) and head == upstream_head and not index
        detail = f"HEAD={head} upstream={upstream} upstream_HEAD={upstream_head} staged={bool(index)}"
    except Exception as exc:
        git_ok = False
        detail = f"{type(exc).__name__}: {exc}"
    _add(checks, "GIT_FROZEN_HEAD", git_ok, detail)
    if not git_ok:
        errors.append("GIT_FROZEN_HEAD")

    try:
        tag_target = str(_git(root, "rev-list", "-n", "1", stage.release_tag)).strip()
        tag_ok = tag_target == stage.prior_tag_target and bool(re.fullmatch(r"[0-9a-f]{40}", tag_target))
        detail = f"{stage.release_tag} -> {tag_target}; configured prior target={stage.prior_tag_target}"
    except Exception as exc:
        tag_ok = False
        detail = f"{type(exc).__name__}: {exc}"
    _add(checks, "PRIOR_TAG_TARGET", tag_ok, detail)
    if not tag_ok:
        errors.append("PRIOR_TAG_TARGET")

    # Release-source classifier is the authority for allowing post-freeze control
    # files.  If it is unavailable, validation fails closed.
    try:
        from runtime.release_identity import _release_dirty_state  # type: ignore
        dirty = _release_dirty_state(root)
        classifier_errors = list(dirty.get("classifier_errors", ()))
        blocking = sorted(set(dirty.get("blocking_paths", ())), key=str.casefold)
        dirty_ok = not classifier_errors and not blocking
        detail = "no blocking source drift" if dirty_ok else f"blocking={blocking!r}; classifier_errors={classifier_errors!r}"
        extra = {"blocking_paths": blocking, "classifier_errors": classifier_errors, "mutable_control_paths": sorted(set(dirty.get("mutable_paths", ())), key=str.casefold)}
    except Exception as exc:
        dirty_ok = False
        detail = f"{type(exc).__name__}: {exc}"
        extra = {}
    _add(checks, "RELEASE_SOURCE_CLASSIFICATION", dirty_ok, detail, **extra)
    if not dirty_ok:
        errors.append("RELEASE_SOURCE_CLASSIFICATION")

    # Derive timeout floors from the current test topology.  A candidate cannot
    # override these downward.
    try:
        from runtime.test_profiles import governed_full_profile_timeout_envelope, governed_section_timeout_envelope  # type: ignore
        section_floor = int(governed_section_timeout_envelope(root)["__sequential_stage__"])
        profile_floor = int(governed_full_profile_timeout_envelope(root)["__sequential_stage__"])
        timeout_ok = automation.timeouts_seconds["sections"] >= section_floor and automation.timeouts_seconds["full_profile"] >= profile_floor
        detail = f"sections={automation.timeouts_seconds['sections']}>={section_floor}; full_profile={automation.timeouts_seconds['full_profile']}>={profile_floor}"
    except Exception as exc:
        timeout_ok = False
        detail = f"{type(exc).__name__}: {exc}"
    _add(checks, "GOVERNED_TIMEOUT_ENVELOPES", timeout_ok, detail)
    if not timeout_ok:
        errors.append("GOVERNED_TIMEOUT_ENVELOPES")

    # Run the current candidate readiness aggregate.  It is read-only when the
    # candidate is fresh; it may inspect current predecessor/repair state.
    try:
        from scripts.run_release_candidate import readiness  # type: ignore
        ready = readiness(automation)
        ready_ok = ready.get("valid") is True
        detail = "candidate readiness is green" if ready_ok else json.dumps(ready.get("errors", []), ensure_ascii=False)
    except Exception as exc:
        ready_ok = False
        detail = f"{type(exc).__name__}: {exc}"
    _add(checks, "CURRENT_READINESS", ready_ok, detail)
    if not ready_ok:
        errors.append("CURRENT_READINESS")

    after = _status_snapshot(root)
    nonmutating = before == after
    _add(checks, "VALIDATOR_NONMUTATION", nonmutating, "Git status unchanged" if nonmutating else "validator changed repository status")
    if not nonmutating:
        errors.append("VALIDATOR_NONMUTATION")

    unique_errors = list(dict.fromkeys(errors))
    return {
        "schema_version": SCHEMA,
        "candidate_id": automation.candidate_id,
        "valid": not unique_errors,
        "allow_started": allow_started,
        "errors": unique_errors,
        "checks": checks,
        "canonical_step_order": list(STEP_ORDER),
        "owner_command_counts": {step: CONTRACT_BY_STEP[step].owner_command_count for step in STEP_ORDER},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--automation-config", type=Path, required=True)
    parser.add_argument("--stage-config", type=Path, required=True)
    parser.add_argument("--allow-started", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(args.automation_config, args.stage_config, allow_started=args.allow_started)
    except Exception as exc:
        result = {
            "schema_version": SCHEMA,
            "valid": False,
            "errors": ["VALIDATOR_EXCEPTION"],
            "checks": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
