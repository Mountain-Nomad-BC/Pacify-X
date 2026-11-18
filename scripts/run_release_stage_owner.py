"""Plan, check, or execute exactly one parameterized release-stage owner."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Protocol
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.certification_contract import (  # noqa: E402
    RELEASE_STAGE_PHASES as STAGE_PHASES,
    RELEASE_STAGES as STAGES,
    STAGE_OWNER_PHASES as PHASES,
    STAGE_OWNER_STEPS as STEPS,
    STAGE_RECEIPT_CANDIDATE_FIELDS,
    STAGE_RECEIPT_SCHEMAS,
)


SCHEMA = "px.release-stage-owner-config/1.0"
CURRENT_SCHEMA = "px.release-stage-owner-config/2.0"


class OwnerBlocked(RuntimeError):
    pass


class OwnerNotAdmitted(OwnerBlocked):
    """Read-only preflight rejected execution before the owner was consumed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    from runtime.hash_utils import file_sha256
    return file_sha256(path)


def _original_path(path: Path, label: str) -> Path:
    from runtime.archive_io import reject_path_links
    try:
        reject_path_links(path)
        return path.resolve()
    except (OSError, ValueError) as error:
        raise OwnerBlocked(f"unsafe or linked {label} path") from error


def load_object(path: Path) -> dict[str, Any]:
    _original_path(path, "JSON input")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OwnerBlocked(f"expected JSON object: {path}")
    return value


def inside(root: Path, raw: object, label: str) -> Path:
    source = Path(str(raw or ""))
    if not str(source) or ".." in source.parts:
        raise OwnerBlocked(f"unsafe {label} path")
    nominal = Path(os.path.abspath(source if source.is_absolute() else root / source))
    try:
        relative = nominal.relative_to(root)
    except ValueError as exc:
        raise OwnerBlocked(f"{label} escapes repository") from exc
    current = root
    for part in relative.parts:
        current /= part
        try:
            flags = int(getattr(current.lstat(), "st_file_attributes", 0))
        except FileNotFoundError:
            flags = 0
        if current.is_symlink() or flags & int(
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise OwnerBlocked(f"{label} traverses a symlink/reparse point: {current}")
    path = nominal.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OwnerBlocked(f"{label} escapes repository") from exc
    return path


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise OwnerBlocked(f"output parent is a symlink: {path.parent}")
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.new")
    with prepared.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(prepared, path)


@dataclass(frozen=True)
class Config:
    root: Path
    candidate_id: str
    predecessor_id: str
    artifact: Path
    artifact_sha256: str
    artifact_size: int
    artifact_mtime_ns: int
    evidence_dir: Path
    log_dir: Path
    path_manifest: Path
    commit_message: str
    release_tag: str
    prior_tag_target: str
    zip_entry_count: int
    installed_dir: Path
    code_command: Path
    installed_tree_digest: str
    installed_version: str
    installable_entry_count: int
    identity_kind: str = "git"
    source_freeze_reference: dict | None = None
    artifact_state: str = "committed_legacy"
    artifact_type: str = "vsix"
    artifact_build_owner: str = ""
    install_state: str = "observed_legacy"

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = load_object(path)
        if raw.get("schema_version") not in (SCHEMA,CURRENT_SCHEMA):
            raise OwnerBlocked(f"config must use {SCHEMA}")
        root_raw = Path(str(raw.get("root") or ""))
        root = _original_path(
            root_raw if root_raw.is_absolute() else path.parent / root_raw, "root"
        )
        artifact = raw.get("artifact")
        identity = raw.get("identity")
        install = raw.get("install")
        if (
            not isinstance(artifact, dict)
            or not isinstance(identity, dict)
            or not isinstance(install, dict)
        ):
            raise OwnerBlocked("artifact, identity, and install objects are required")
        current = raw["schema_version"] == CURRENT_SCHEMA
        from runtime.release_source_identity import require_release_configuration_mode
        require_release_configuration_mode(root, current=current)
        if current:
            from runtime.release_source_identity import current_campaign
            if not current_campaign(root) or set(identity)!={"identity_kind","source_freeze"} or identity.get("identity_kind")!="standalone_current_campaign":
                raise OwnerBlocked("current owner config requires exact native source identity; no Git fields")
            reference=identity["source_freeze"]
            if type(reference) is not dict or set(reference)!={"path","sha256"}:
                raise OwnerBlocked("current config requires exact final source-freeze reference")
        elif "identity_kind" in identity or "source_freeze" in identity:
            raise OwnerBlocked("tagged source identity requires current config schema")
        if current:
            if set(artifact)!={"state","path","type","build_owner"} or artifact.get("state")!="planned" or artifact.get("type")!="vsix" or artifact.get("build_owner")!="extension/scripts/package-vsix.js":
                raise OwnerBlocked("current early artifact must be an exact planned VSIX producer locator")
            if set(install)!={"state","directory","code_command"} or install.get("state")!="planned":
                raise OwnerBlocked("current early installation requires planned locators, never invented installed evidence")
        candidate = str(raw.get("candidate_id") or "").strip()
        if current:
            from runtime.release_source_identity import release_configuration_relative
            if path.resolve()!=root/release_configuration_relative(candidate,"stage-owner"):
                raise OwnerBlocked("current stage config must migrate to its closed native derived-control locator")
        predecessor = str(raw.get("predecessor_id") or "").strip()
        digest = str(artifact.get("sha256") or "")
        result = cls(
            root=root,
            candidate_id=candidate,
            predecessor_id=predecessor,
            artifact=inside(root, artifact.get("path"), "artifact"),
            artifact_sha256=digest,
            artifact_size=int(artifact.get("size") or 0),
            artifact_mtime_ns=int(artifact.get("mtime_ns") or 0),
            evidence_dir=inside(root, raw.get("evidence_dir"), "evidence_dir"),
            log_dir=inside(root, raw.get("log_dir"), "log_dir"),
            path_manifest=inside(root, reference["path"] if current else identity.get("path_manifest"), "path_manifest"),
            commit_message=str(identity.get("commit_message") or "").strip(),
            release_tag=str(identity.get("release_tag") or "").strip(),
            prior_tag_target=str(identity.get("prior_tag_target") or "").strip(),
            zip_entry_count=int(artifact.get("entry_count") or 0),
            installed_dir=_original_path(Path(str(install.get("directory") or "")), "installation"),
            code_command=_original_path(Path(str(install.get("code_command") or "")), "VS Code executable"),
            installed_tree_digest=str(install.get("tree_digest") or ""),
            installed_version=str(install.get("version") or "").strip(),
            installable_entry_count=int(install.get("entry_count") or 0),
            identity_kind="standalone_current_campaign" if current else "git",
            source_freeze_reference=dict(reference) if current else None,
            artifact_state="planned" if current else "committed_legacy",
            artifact_build_owner=artifact["build_owner"] if current else "",
            install_state="planned" if current else "observed_legacy",
        )
        if (
            not candidate
            or not predecessor
            or candidate == predecessor
            or (not current and (not re.fullmatch(r"[0-9a-f]{64}", digest)
            or result.artifact_size <= 0
            or result.artifact_mtime_ns <= 0
            or result.zip_entry_count <= 0
            or result.installable_entry_count <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", result.installed_tree_digest)
            or not result.installed_version))
            or (not current and (not result.commit_message
                or not result.release_tag.startswith("v") or len(result.prior_tag_target) != 40))
        ):
            raise OwnerBlocked("config contains an incomplete exact owner contract")
        return observe_completed_stages(result) if current else result

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def release(config: Config) -> dict[str, Any]:
    from runtime.release_campaign import release_state_relative
    return load_object(config.root / release_state_relative(config.root))


def private_installation_root(config: Config) -> Path:
    from runtime.release_source_identity import release_private_installation_relative
    return config.root / release_private_installation_relative(config.candidate_id)


def extension_identity(config: Config) -> dict[str, str]:
    from runtime.archive_io import reject_path_links, portable_member_name
    from runtime.json_io import load_json_object
    path = config.root / "extension/package.json"
    reject_path_links(path)
    package = load_json_object(path, max_bytes=1024 * 1024)
    for key in ("name", "publisher"):
        if type(package.get(key)) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", package[key]):
            raise OwnerBlocked("current package requires a portable extension identity")
    version = package.get("version")
    if type(version) is not str or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise OwnerBlocked("current package version is invalid")
    portable_member_name(f"{package['name']}-{version}.vsix", allow_directory=False)
    return {"name": package["name"], "publisher": package["publisher"], "version": version,
            "extension_id": f"{package['publisher']}.{package['name']}"}


def observe_package(config: Config) -> dict[str, Any]:
    """Inspect one bounded VSIX image without extracting any archive path."""
    from runtime.archive_io import read_archive_bytes, validated_zip, read_stream_bytes, reject_path_links
    from runtime.json_io import decode_json_object
    from xml.etree import ElementTree
    identity = extension_identity(config)
    before = config.artifact.stat()
    image = read_archive_bytes(config.artifact)
    with validated_zip(image) as (archive, rows):
        def member(name):
            with archive.open(name) as stream:
                return bytes(read_stream_bytes(stream, max_bytes=1024 * 1024))
        package = decode_json_object(member("extension/package.json"), max_bytes=1024 * 1024)
        if any(package.get(key) != identity[key] for key in ("name", "publisher", "version")):
            raise OwnerBlocked("built VSIX extension identity differs from frozen source")
        main = package.get("main")
        if type(main) is not str or main != "./src/extension.bundle.js":
            raise OwnerBlocked("built VSIX does not select its generated bundle")
        archive.getinfo("extension/src/extension.bundle.js")
        manifest = member("extension.vsixmanifest")
        if b"\0" in manifest or b"<!DOCTYPE" in manifest.upper() or b"<!ENTITY" in manifest.upper():
            raise OwnerBlocked("VSIX manifest declarations are forbidden")
        element = ElementTree.fromstring(manifest)
        declared = element.find("{*}Metadata/{*}Identity")
        if declared is None or any(declared.get(key) != identity[value] for key, value in (
            ("Id", "name"), ("Publisher", "publisher"), ("Version", "version"))):
            raise OwnerBlocked("VSIX manifest identity differs from frozen source")
        if archive.testzip() is not None:
            raise OwnerBlocked("built VSIX failed CRC verification")
        installable = sum(not row.is_dir() and row.filename.startswith("extension/") for row in rows) + 1
        if any(row.filename.casefold() == "extension/.vsixmanifest" for row in rows):
            raise OwnerBlocked("VSIX contains an installed manifest collision")
        count = len(rows)
    reject_path_links(config.artifact)
    after = config.artifact.stat()
    if any(getattr(before, field) != getattr(after, field) for field in (
        "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")) or len(image) != after.st_size:
        raise OwnerBlocked("VSIX changed during bounded observation")
    return {"sha256": hashlib.sha256(image).hexdigest(), "size": len(image), "mtime_ns": after.st_mtime_ns,
            "entry_count": count, "installable_entry_count": installable,
            "version": identity["version"], "extension_id": identity["extension_id"]}


def with_observed_package(config: Config, observation: Mapping[str, Any]) -> Config:
    return replace(config, artifact_state="observed_current", artifact_sha256=observation["sha256"],
        artifact_size=observation["size"], artifact_mtime_ns=observation["mtime_ns"],
        zip_entry_count=observation["entry_count"], installable_entry_count=observation["installable_entry_count"],
        installed_version=observation["version"])


def vscode_cli_entrypoint(executable: Path) -> Path:
    """Resolve only the traditional layout or the installed Windows wrapper's exact target."""
    from runtime.archive_io import reject_path_links
    reject_path_links(executable)
    direct = executable.parent / "resources/app/out/cli.js"
    reject_path_links(direct)
    if direct.is_file():
        return direct
    wrapper = executable.parent / "bin/code.cmd"
    reject_path_links(wrapper)
    if not wrapper.is_file() or wrapper.stat().st_size > 65536:
        raise OwnerBlocked("native VS Code CLI entrypoint is unavailable")
    with wrapper.open("rb") as stream:
        image = stream.read(65537)
    if len(image) > 65536:
        raise OwnerBlocked("native VS Code wrapper exceeds its bounded size")
    targets = []
    for line in image.decode("utf-8-sig").splitlines():
        match = re.fullmatch(r'"%~dp0\.\.\\Code\.exe" "%~dp0\.\.\\([0-9a-f]{10})\\resources\\app\\out\\cli\.js" %\*', line.strip())
        if match:
            targets.append(executable.parent / match[1] / "resources/app/out/cli.js")
    if len(targets) != 1:
        raise OwnerBlocked("native VS Code wrapper must identify exactly one bounded CLI entrypoint")
    cli = targets[0]
    reject_path_links(cli)
    if not cli.is_file():
        raise OwnerBlocked("native VS Code wrapper CLI entrypoint is unavailable")
    return cli


def vscode_cli_argv(config: Config, *arguments: str) -> list[str]:
    from runtime.archive_io import reject_path_links
    reject_path_links(config.code_command)
    if not config.code_command.is_file():
        raise OwnerBlocked("configured native VS Code executable is unavailable")
    command = [str(config.code_command)]
    if os.name == "nt":
        if config.code_command.suffix.lower() != ".exe":
            raise OwnerBlocked("Windows private installation requires the native VS Code executable")
        cli = vscode_cli_entrypoint(config.code_command)
        command.append(str(cli))
    return [*command, *arguments]


def current_realization_preflight(config: Config, step: str) -> dict[str, Any]:
    from runtime.archive_io import reject_path_links
    if config.identity_kind != "standalone_current_campaign" or step not in {"package", "install"}:
        raise OwnerBlocked("current package/install owner requires its closed current contract")
    identity = extension_identity(config)
    expected = config.root / "extension/dist" / f"{identity['name']}-{identity['version']}.vsix"
    if config.artifact != expected or config.artifact_build_owner != "extension/scripts/package-vsix.js":
        raise OwnerBlocked("planned artifact must use its exact extension producer/version locator")
    private = private_installation_root(config)
    installed = private / "extensions" / f"{identity['extension_id']}-{identity['version']}"
    if config.installed_dir != installed:
        raise OwnerBlocked("current installation must use the candidate's private extension/profile root")
    reject_path_links(config.artifact)
    reject_path_links(private)
    if private.exists():
        raise OwnerBlocked("private installation output already exists; no replacement or replay")
    vscode_cli_argv(config)
    if step == "package":
        node = shutil.which("node")
        if not node:
            raise OwnerBlocked("native Node package producer is unavailable")
        reject_path_links(Path(node))
        if config.artifact.exists():
            raise OwnerBlocked("issued VSIX already exists; select a fresh source version")
        if not (config.root / config.artifact_build_owner).is_file():
            raise OwnerBlocked("declared package producer is unavailable")
    elif config.artifact_state != "observed_current":
        raise OwnerBlocked("installation requires an authenticated observed package")
    return identity


def observe_completed_stages(config: Config) -> Config:
    """Hydrate current observations only from authenticated, passed native claims."""
    from runtime.archive_io import reject_path_links
    from runtime.json_io import load_json_object
    from runtime.release_campaign import release_campaign_status
    from runtime.studio_authority import StudioAuthorityStore
    current = release(config)
    stages = current.get("stages", {})
    if current.get("campaign_id") != config.candidate_id or stages.get("package", {}).get("status") != "passed":
        return config
    status = release_campaign_status(config.root, verify_source=True)
    if status.get("valid") is not True or status.get("campaign_id") != config.candidate_id:
        raise OwnerBlocked("observed release stages lack a current native source identity")
    authority = StudioAuthorityStore.open_existing(config.root)
    for stage in ("package", "install"):
        native = stages.get(stage, {})
        if native.get("status") != "passed":
            break
        path = config.evidence_dir / f"{config.candidate_id}-{stage}.json"
        reject_path_links(path)
        body = authority.verify_receipt(load_json_object(path, max_bytes=4 * 1024 * 1024))
        mode = body.get("realization", {})
        kernel = status["identity"]
        if (body.get("valid") is not True or body.get("campaign_id") != config.candidate_id
            or body.get("claim_id") != native.get("claim_id")
            or any(body.get(key) != kernel.get(key) for key in (
                "release_identity_sha256", "source_product_digest", "source_harness_digest"))
            or mode.get("schema_version") != "px.current-release-realization/1.0"
            or mode.get("stage") != stage or mode.get("source_freeze") != config.source_freeze_reference
            or mode.get("owner_command", {}).get("valid") is not True):
            raise OwnerBlocked("current realization receipt differs from its native stage/source")
        command = mode["owner_command"]
        log = inside(config.root, command.get("path"), "realization command log")
        from runtime.json_io import read_bounded_bytes
        log_image = read_bounded_bytes(log, max_bytes=2 * 1024 * 1024)
        if hashlib.sha256(log_image).hexdigest() != command.get("sha256") or len(log_image) != command.get("size"):
            raise OwnerBlocked("current realization command log differs from its signed receipt")
        if body.get("schema_version") != STAGE_RECEIPT_SCHEMAS[stage] or (
            stage == "package" and (body.get("artifact_rebuilt") is not True or body.get("artifact_touched") is not True)) or (
            stage == "install" and (body.get("machine_mutated") is not True or body.get("install_command_executed") is not True)):
            raise OwnerBlocked("current realization receipt contradicts its executed effects")
        observed = observe_package(config)
        if observed != body.get("artifact_observation") or body.get("artifact") != {
            "path": config.relative(config.artifact), "sha256": observed["sha256"], "size": observed["size"]}:
            raise OwnerBlocked("realization receipt differs from actual VSIX bytes")
        config = with_observed_package(config, observed)
        if stage == "install":
            observation = body.get("installation_observation", {})
            files, links, tree_digest = ProductionEffects().tree(config.installed_dir)
            if (observation != {"directory": str(config.installed_dir), "tree_digest": tree_digest,
                "file_count": len(files), "version": config.installed_version,
                "profile": str(private_installation_root(config) / "user-data")}
                or links or len(files) != config.installable_entry_count
                or body.get("tree_digest_after") != tree_digest):
                raise OwnerBlocked("realization receipt differs from actual installed bytes")
            config = replace(config, install_state="observed_current", installed_tree_digest=tree_digest)
    return config


def repair(config: Config) -> dict[str, Any]:
    from runtime.project_revision_succession import current_campaign_path
    return load_object(current_campaign_path(config.root))


def identity_manifest(config: Config) -> tuple[list[str], list[str]]:
    """Validate the exact pre-identity Git source and mutable-control sets."""

    if config.identity_kind == "standalone_current_campaign":
        from runtime.release_repository_context import verify_source_anchor
        verify_source_anchor(config.root,config.source_freeze_reference,require_live=True)
        return [],[]
    from runtime.release_identity import _release_dirty_state

    if not config.path_manifest.is_file() or config.path_manifest.is_symlink():
        raise OwnerBlocked("identity path manifest is not a regular file")
    manifest = load_object(config.path_manifest)
    paths = manifest.get("paths")
    mutable_paths = manifest.get("mutable_paths", [])
    if (
        manifest.get("schema_version")
        != "px.release-identity-path-manifest/1.0"
        or manifest.get("candidate_id") != config.candidate_id
        or not isinstance(paths, list)
        or paths != sorted(set(paths), key=str.casefold)
        or not isinstance(mutable_paths, list)
        or mutable_paths != sorted(set(mutable_paths), key=str.casefold)
        or set(paths) & set(mutable_paths)
        or any(
            not isinstance(path, str) or not path or ".." in Path(path).parts
            for path in [*paths, *mutable_paths]
        )
    ):
        raise OwnerBlocked(
            "identity manifest must bind the candidate and contain sorted, "
            "disjoint, safe source/mutable paths"
        )
    dirty = _release_dirty_state(config.root)
    if dirty.get("classifier_errors"):
        raise OwnerBlocked("release source classification is invalid")
    if paths:
        raise OwnerBlocked(
            "identity cannot commit source: certification requires a pre-aligned clean HEAD"
        )
    if set(dirty.get("blocking_paths", ())) != set(paths):
        raise OwnerBlocked(
            "blocking source changes differ from the explicit identity manifest"
        )
    expected_mutable_paths = set(dirty.get("mutable_control_paths", ()))
    expected_mutable_paths.add(config.relative(config.path_manifest))
    if expected_mutable_paths != set(mutable_paths):
        raise OwnerBlocked(
            "mutable control changes differ from the explicit identity manifest"
        )
    return paths, mutable_paths


def invalid_active_predecessor_kind(
    config: Config, current_release: Mapping[str, Any]
) -> str | None:
    """Classify only structurally valid campaigns invalidated by source drift."""

    if (
        current_release.get("state") != "active"
        or current_release.get("apply_count") != 1
        or not isinstance(current_release.get("identity"), dict)
        or current_release.get("active_claim") is not None
    ):
        return None
    stages = current_release.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        return None
    statuses = [
        stages[name].get("status") if isinstance(stages.get(name), dict) else None
        for name in STAGES
    ]
    from runtime.release_campaign import release_campaign_status

    structural = release_campaign_status(config.root, verify_source=False)
    source = release_campaign_status(config.root, verify_source=True)
    if (
        structural.get("valid") is not True
        or source.get("valid") is not False
        or not source.get("errors")
    ):
        return None
    if all(status == "pending" for status in statuses):
        return "unused_invalid_identity"
    passed = next(
        (index for index, status in enumerate(statuses) if status != "passed"),
        len(statuses),
    )
    if 0 < passed < len(statuses) and statuses == (
        ["passed"] * passed + ["pending"] * (len(statuses) - passed)
    ):
        return "invalid_active_with_retained_passes"
    return None


def resource_postcondition(config: Config) -> dict[str, Any]:
    """Allow only this supervised child while it is proving its own effects."""

    from runtime.resource_lifecycle import ResourceLedger, _resource_status_records

    ledger_path = config.root / ".agentic_engineering_os_px/resource-lifecycle/ledger.json"
    records = ResourceLedger(ledger_path).observe()
    status = _resource_status_records(records)
    active = [row for row in records if row.active is True]
    exact_self = (
        len(active) == 1
        and active[0].resource_type == "process"
        and active[0].run_id == config.candidate_id
        and active[0].creator == "scripts.run_release_candidate"
        and os.environ.get("PX_RELEASE_OWNER_RUN_ID") == config.candidate_id
    )
    valid = (
        status.get("valid") is True
        and status.get("active_paths") == 0
        and status.get("reclaimable_paths") == 0
        and status.get("cleanup_failures") == 0
        and (status.get("active_processes") == 0 or exact_self)
    )
    return {**status, "active_records": len(active), "exact_supervised_self": exact_self, "valid": valid}


def required_section_evidence(status: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a sections receipt to every current required section, without fixed counts."""
    names, rows = status.get("required_sections"), status.get("sections")
    if (status.get("valid") is not True or not isinstance(names, list) or not names
            or any(type(name) is not str or not name for name in names)
            or len(names) != len(set(names)) or not isinstance(rows, list)):
        raise OwnerBlocked("required governed sections are not current")
    evidence = []
    for name in names:
        matches = [row for row in rows if isinstance(row, dict) and row.get("section") == name]
        if (len(matches) != 1 or matches[0].get("current") is not True
                or not isinstance(matches[0].get("input_sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", matches[0]["input_sha256"]) is None):
            raise OwnerBlocked("required section lacks unique current input evidence: " + name)
        evidence.append({"section": name, "input_sha256": matches[0]["input_sha256"]})
    return {"all_required_sections_current": True, "required_section_count": len(names),
            "required_section_inputs": evidence}


def check(config: Config, step: str) -> dict[str, Any]:
    from runtime.release_campaign import cleared_campaign_can_be_superseded

    errors: list[str] = []
    if step not in STEPS:
        errors.append("unsupported step")
    if config.artifact_state == "planned":
        if step == "package" and config.identity_kind == "standalone_current_campaign":
            try:
                current_realization_preflight(config, step)
            except (OSError, ValueError, OwnerBlocked) as error:
                errors.append("planned artifact cannot satisfy current package preflight: " + str(error))
        elif step not in {"archive_clear", "reconcile", "identity", "sections", "full_profile", "validate"}:
            errors.append("planned artifact cannot satisfy package/install or downstream artifact evidence")
    elif not config.artifact.is_file() or config.artifact.is_symlink():
        errors.append("artifact is not a regular file")
    else:
        info = config.artifact.stat()
        if (sha256(config.artifact), info.st_size, info.st_mtime_ns) != (
            config.artifact_sha256,
            config.artifact_size,
            config.artifact_mtime_ns,
        ):
            errors.append("artifact identity differs from config")
    if step == "identity":
        try:
            identity_manifest(config)
        except (OwnerBlocked, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"identity manifest is not ready: {type(exc).__name__}: {exc}")
    try:
        current_repair = repair(config)
        current_release = release(config)
        archive_recovery_phase = None
        active_kind = None
        if step == "archive_clear" and current_release.get("state") == "failed":
            failed_stages = [
                name
                for name, record in current_release.get("stages", {}).items()
                if isinstance(record, dict) and record.get("status") == "failed"
            ]
            if len(failed_stages) == 1 and failed_stages[0] in STAGE_PHASES:
                archive_recovery_phase = STAGE_PHASES[failed_stages[0]]
        elif step == "archive_clear" and current_release.get("state") == "active":
            active_kind = invalid_active_predecessor_kind(config, current_release)
            if active_kind == "unused_invalid_identity":
                archive_recovery_phase = "revision_reconciled"
            elif active_kind == "invalid_active_with_retained_passes":
                passed_stages = [
                    name
                    for name in STAGES
                    if current_release["stages"][name].get("status") == "passed"
                ]
                archive_recovery_phase = STAGE_PHASES[STAGES[len(passed_stages)]]
        elif step == "archive_clear" and current_release.get("state") == "cleared":
            if cleared_campaign_can_be_superseded(current_release):
                archive_recovery_phase = "revision_reconciled"
        repair_phase_valid = current_repair.get("phase") == PHASES.get(
            step, (None,)
        )[0] or current_repair.get("phase") == archive_recovery_phase
        if (
            not str(current_repair.get("campaign_id") or "").strip()
            or (
                step != "archive_clear"
                and current_release.get("repair_campaign_id")
                != current_repair.get("campaign_id")
            )
            or not repair_phase_valid
            or current_repair.get("intake_open") is not False
            or current_repair.get("unresolved") != []
        ):
            errors.append(f"repair campaign phase is not exact for {step}")
        if step == "archive_clear":
            already_established = already_established_successor(config, current_release)
            if (
                not already_established
                and (
                    current_release.get("campaign_id") != config.predecessor_id
                    or current_release.get("active_claim") is not None
                    or current_release.get("state") not in {"failed", "cleared", "active"}
                    or (
                        current_release.get("state") == "cleared"
                        and (
                            current_release.get("apply_count") != 0
                            or current_release.get("identity") is not None
                            or not cleared_campaign_can_be_superseded(current_release)
                        )
                    )
                    or (
                        current_release.get("state") == "active"
                        and active_kind not in {
                            "unused_invalid_identity",
                            "invalid_active_with_retained_passes",
                        }
                    )
                )
            ):
                errors.append(
                    "archive_clear requires a terminal failed, unused cleared, "
                    "or source-invalid active predecessor"
                )
        elif step in {"reconcile", "identity"}:
            if (
                current_release.get("campaign_id") != config.candidate_id
                or current_release.get("state") != "cleared"
                or current_release.get("apply_count") != 0
                or current_release.get("identity") is not None
            ):
                errors.append(f"{step} requires cleared candidate")
        else:
            stages = current_release.get("stages", {})
            index = STAGES.index(step)
            if (
                current_release.get("campaign_id") != config.candidate_id
                or current_release.get("state") != "active"
                or current_release.get("apply_count") != 1
                or tuple(stages) != STAGES
                or current_release.get("active_claim") is not None
                or stages.get(step, {}).get("status") != "pending"
                or any(
                    stages[name].get("status") != "passed" for name in STAGES[:index]
                )
            ):
                errors.append(f"{step} release stage/predecessors are not exact")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"control plane unreadable: {type(exc).__name__}")
    existing_receipt = config.evidence_dir / f"{config.candidate_id}-{step}.json"
    existing_log = config.log_dir / f"{config.candidate_id}-{step}.log"
    if existing_receipt.exists():
        try:
            existing = load_object(existing_receipt)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("existing owner receipt is unreadable; replay is forbidden")
        else:
            if (
                existing.get("schema_version")
                == "px.release-stage-owner-terminal-marker/1.0"
                and existing.get("status") == "running"
            ):
                errors.append(
                    "owner has a retained running marker; replay is forbidden; "
                    f"inspect owner_pid={existing.get('owner_pid')!r} "
                    f"attempt_id={existing.get('attempt_id')!r}"
                )
            else:
                errors.append("fresh owner receipt already exists; replay is forbidden")
    if existing_log.exists():
        errors.append("fresh owner log already exists; replay is forbidden")
    return {
        "schema_version": "px.release-stage-owner-check/1.0",
        "candidate_id": config.candidate_id,
        "step": step,
        "valid": not errors,
        "errors": errors,
    }


def plan(config: Config, step: str) -> dict[str, Any]:
    return {
        "schema_version": "px.release-stage-owner-plan/1.0",
        "mode": "plan",
        "effects": False,
        "one_step": True,
        "valid": True,
        "candidate_id": config.candidate_id,
        "step": step,
        "phase_before": PHASES.get(step, (None, None))[0],
        "phase_after": PHASES.get(step, (None, None))[1],
    }


class Effects(Protocol):
    def execute(self, step: str, config: Config) -> Mapping[str, Any]: ...
    def verify(self, step: str, config: Config) -> None: ...


class ProductionEffects:
    def current_realization(self, config: Config, step: str) -> Mapping[str, Any]:
        """Create one private package/install under the native, non-replayable claim."""
        from runtime.release_process_custody import require_release_host, require_release_admission
        from runtime.release_campaign import claim_release_stage, finish_release_stage
        from runtime.studio_authority import StudioAuthorityStore
        from runtime.resource_lifecycle import ResourceManager, ResourceClassification, RunState
        require_release_host(config.root)
        require_release_admission(config.root, os.environ.get("PX_RELEASE_ADMISSION_EVENT_ID"), (
            ("read", str(config.root)), ("write", str(config.evidence_dir)),
            ("write", str(config.log_dir)), ("execute", "runtime")))
        authority = StudioAuthorityStore.open_existing(config.root)
        identity = current_realization_preflight(config, step)
        private = private_installation_root(config)
        if step == "install":
            require_release_admission(config.root, os.environ.get("PX_RELEASE_INSTALL_ADMISSION_EVENT_ID"),
                                      (("install", str(private)),))
        path = config.evidence_dir / f"{config.candidate_id}-{step}.json"
        self.probe_output(path)
        claim = claim_release_stage(config.root, step)
        finished = False
        installation_manager = None
        installation_run = "private-installation-" + hashlib.sha256(config.candidate_id.encode()).hexdigest()
        receipt_written = False
        try:
            atomic_json(path, {"schema_version": "px.release-stage-owner-terminal-marker/1.0",
                "candidate_id": config.candidate_id, "step": step, "claim_id": claim["claim_id"],
                "status": "running", "valid": False, "retry_policy": "no-replay; inspect canonical state"})
            if step == "package":
                command = self.command(config, "package-build", [shutil.which("node"),
                    str(config.root / config.artifact_build_owner)], timeout_seconds=600)
                observation = observe_package(config)
                config = with_observed_package(config, observation)
                payload = self.package_audit(config, claim)
                payload.update(artifact_rebuilt=True, artifact_touched=True)
            else:
                observation = observe_package(config)
                if (observation["sha256"], observation["size"], observation["mtime_ns"]) != (
                    config.artifact_sha256, config.artifact_size, config.artifact_mtime_ns):
                    raise OwnerBlocked("package changed before private installation")
                installation_manager = ResourceManager(config.root / ".agentic_engineering_os_px/resource-lifecycle/ledger.json")
                private.parent.mkdir(parents=True, exist_ok=True)
                installation_manager.register_path(private, allowed_cleanup_root=private.parent,
                    project_id=str(config.root), run_id=installation_run, lane_id="install",
                    creator="native-release-owner", classification=ResourceClassification.PROTECTED,
                    retention_required=True, expected_cleanup_event="explicit owner retirement only")
                private.mkdir(exist_ok=False)
                command = self.command(config, "install-realize", vscode_cli_argv(config,
                    "--user-data-dir", str(private / "user-data"), "--extensions-dir", str(private / "extensions"),
                    "--install-extension", str(config.artifact)), timeout_seconds=900)
                files, links, tree_digest = self.tree(config.installed_dir)
                if links or len(files) != config.installable_entry_count:
                    raise OwnerBlocked("private installation tree denominator differs from observed package")
                config = replace(config, installed_tree_digest=tree_digest, install_state="observed_current")
                payload = self.install_audit(config, claim)
                payload.update(machine_mutated=True, install_command_executed=True,
                    installation_observation={"directory": str(config.installed_dir), "tree_digest": tree_digest,
                        "file_count": len(files), "version": identity["version"],
                        "profile": str(private / "user-data")})
            if payload.get("valid") is not True or command.get("valid") is not True:
                raise OwnerBlocked(f"current {step} did not reach its exact observed postcondition")
            payload.update(artifact_observation=observation, realization={
                "schema_version": "px.current-release-realization/1.0", "stage": step,
                "source_freeze": config.source_freeze_reference, "owner_command": command})
            if installation_manager is not None:
                installation_manager.mark_run_ended(installation_run, RunState.COMPLETED,
                    retain_reason="Private installed extension and profile; no automatic deletion authority")
            signed = authority.sign_receipt(payload)
            authority.verify_receipt(signed)
            terminal = finish_release_stage(config.root, stage=step, claim_id=claim["claim_id"], passed=True)
            finished = True
            if terminal.get("valid") is not True or terminal.get("stages", {}).get(step, {}).get("status") != "passed":
                raise OwnerBlocked("native realization stage did not pass its final source check")
            reference = self.receipt(config, step, signed)
            receipt_written = True
            self.advance(config, *PHASES[step])
            return reference
        except BaseException as error:
            if not finished:
                finish_release_stage(config.root, stage=step, claim_id=claim["claim_id"], passed=False)
            if not receipt_written:
                atomic_json(path, {"schema_version": "px.release-stage-owner-terminal-marker/1.0",
                    "candidate_id": config.candidate_id, "step": step, "claim_id": claim["claim_id"],
                    "status": "indeterminate" if finished else "failed", "valid": False,
                    "failure_type": type(error).__name__, "retry_policy": "no-replay; inspect canonical state"})
            if installation_manager is not None:
                installation_manager.mark_run_ended(installation_run, RunState.FAILED,
                    retain_reason="Retained private installation attempt; never replay or delete automatically")
            raise

    def probe_output(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise OwnerBlocked(f"fresh owner output already exists: {path}")
        probe = path.with_name(f".{path.name}.{uuid4().hex}.probe")
        try:
            with probe.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write("probe\n")
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if probe.exists():
                probe.unlink()

    def receipt(
        self, config: Config, step: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        path = config.evidence_dir / f"{config.candidate_id}-{step}.json"
        atomic_json(path, dict(payload))
        return {
            "path": config.relative(path),
            "sha256": sha256(path),
            "size": path.stat().st_size,
            "valid": True,
        }

    def advance(self, config: Config, before: str, after: str) -> None:
        from runtime.project_revision_succession import current_campaign_path, current_revision_root
        if current_revision_root(config.root) is not None:
            from runtime.revision_campaign_lifecycle import advance_release_phase
            advance_release_phase(config.root, before=before, after=after,
                                  admission_event_id=os.environ.get("PX_RELEASE_ADMISSION_EVENT_ID"))
            return
        path = current_campaign_path(config.root)
        value = load_object(path)
        if (
            value.get("phase") != before
            or value.get("intake_open") is not False
            or value.get("unresolved") != []
        ):
            raise OwnerBlocked(f"repair phase cannot advance {before} -> {after}")
        value["phase"] = after
        atomic_json(path, value)

    def command(
        self,
        config: Config,
        name: str,
        argv: list[str],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if config.identity_kind == "standalone_current_campaign":
            from runtime.release_process_custody import run_release_command
            return run_release_command(config, name, argv, timeout_seconds=timeout_seconds)
        config.log_dir.mkdir(parents=True, exist_ok=True)
        log = config.log_dir / f"{config.candidate_id}-{name}.log"
        with log.open("x", encoding="utf-8", newline="\n") as stream:
            process = subprocess.Popen(
                argv,
                cwd=config.root,
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                start_new_session=os.name != "nt",
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            try:
                returncode = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                if os.name == "nt":
                    cleanup = subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        shell=False,
                        check=False,
                        timeout=30,
                    )
                    if cleanup.returncode not in {0, 128} and process.poll() is None:
                        raise OwnerBlocked(
                            f"{name} timed out and its process tree did not close"
                        ) from error
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            capture_output=True,
                            shell=False,
                            check=False,
                            timeout=30,
                        )
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                raise OwnerBlocked(
                    f"{name} timed out after {timeout_seconds} seconds"
                ) from error
        if returncode:
            raise OwnerBlocked(f"{name} exited {returncode}")
        return {
            "path": config.relative(log),
            "sha256": sha256(log),
            "size": log.stat().st_size,
        }

    def git(self, config: Config, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=config.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise OwnerBlocked(
                f"git {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}"
            )
        return result.stdout.strip()

    def git_add_paths(self, config: Config, paths: tuple[str, ...]) -> None:
        baseline = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--exit-code"],
            cwd=config.root,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if baseline.returncode:
            raise OwnerBlocked("identity requires an empty Git index before staging")
        if not paths:
            return
        payload = b"\0".join(path.encode("utf-8") for path in paths) + b"\0"
        ignored = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            cwd=config.root,
            input=payload,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if ignored.returncode not in {0, 1}:
            detail = (ignored.stderr or ignored.stdout).decode(
                "utf-8", errors="replace"
            ).strip()
            raise OwnerBlocked(f"git check-ignore path preflight failed: {detail}")
        if ignored.returncode == 0:
            ignored_paths = [
                item.decode("utf-8", errors="replace")
                for item in ignored.stdout.split(b"\0")
                if item
            ]
            raise OwnerBlocked(
                "identity source manifest contains ignored paths: "
                + ", ".join(ignored_paths[:16])
            )
        result = subprocess.run(
            ["git", "add", "--pathspec-from-file=-", "--pathspec-file-nul"],
            cwd=config.root,
            input=payload,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode:
            rollback = subprocess.run(
                ["git", "reset", "--mixed", "HEAD"],
                cwd=config.root,
                capture_output=True,
                timeout=60,
                check=False,
            )
            detail = (result.stderr or result.stdout).decode(
                "utf-8", errors="replace"
            ).strip()
            if rollback.returncode:
                rollback_detail = (rollback.stderr or rollback.stdout).decode(
                    "utf-8", errors="replace"
                ).strip()
                detail += f"; index rollback failed: {rollback_detail}"
            raise OwnerBlocked(f"git add --pathspec-from-file failed: {detail}")

    def identity(self, config: Config) -> Mapping[str, Any]:
        from runtime.release_campaign import apply_release_identity
        from runtime.release_identity import _release_dirty_state, authoritative_version

        if config.identity_kind == "standalone_current_campaign":
            from runtime.release_source_identity import capture_release_source_identity
            identity_manifest(config)
            status=apply_release_identity(config.root,source_freeze_reference=config.source_freeze_reference)
            source=capture_release_source_identity(config.root,version=authoritative_version(config.root))
            if not status.get("valid") or not source.get("valid"):
                raise OwnerBlocked("current final source identity apply failed")
            return self.receipt(config,"identity",{"schema_version":"px.single-identity-transition-receipt/1.0",
                "campaign_id":config.candidate_id,"source_identity":source,"git_acceptance":source["git_acceptance"],
                "commit_created":False,"retag_count":0,"release_identity_sha256":source["release_identity_sha256"],
                "source_product_digest":source["source_product_digest"],"source_harness_digest":source["source_harness_digest"],
                "artifact":{"state":"planned","path":config.relative(config.artifact),"type":config.artifact_type,"build_owner":config.artifact_build_owner},"valid":True})
        paths, mutable_paths = identity_manifest(config)
        self.git_add_paths(config, paths)
        cached = {
            path
            for path in self.git(
                config, "diff", "--cached", "--name-only", "-z", "--no-renames"
            ).split("\0")
            if path
        }
        if cached != set(paths):
            raise OwnerBlocked("Git cached set differs from explicit identity manifest")
        if config.release_tag != f"v{authoritative_version(config.root)}":
            raise OwnerBlocked("release tag differs from authoritative version")
        old_target = self.git(config, "rev-list", "-n", "1", config.release_tag)
        if (
            old_target != config.prior_tag_target
            or self.git(config, "cat-file", "-t", f"refs/tags/{config.release_tag}")
            != "tag"
        ):
            raise OwnerBlocked(
                "existing annotated tag is not at the admitted prior target"
            )
        head = self.git(config, "rev-parse", "HEAD")
        upstream = self.git(config, "rev-parse", "@{u}")
        if head != upstream:
            raise OwnerBlocked(
                "identity requires the frozen source HEAD to equal its upstream HEAD"
            )
        post_commit = _release_dirty_state(config.root)
        if post_commit.get("blocking_paths") or post_commit.get("classifier_errors"):
            raise OwnerBlocked("identity boundary retains blocking release-input drift")
        self.git(
            config,
            "tag",
            "-f",
            "-a",
            config.release_tag,
            "-m",
            f"{config.release_tag} {config.candidate_id}",
            head,
        )
        if self.git(config, "rev-list", "-n", "1", config.release_tag) != head:
            raise OwnerBlocked("authorized one-time retag did not bind HEAD")
        try:
            status = apply_release_identity(config.root)
        except BaseException as exc:
            # If identity application failed before consuming the cleared
            # campaign, restore the admitted prior tag target.  Once the
            # campaign is active, keep the tag on the applied identity so the
            # failed candidate remains internally coherent and auditable.
            try:
                current = release(config)
                if (
                    current.get("state") == "cleared"
                    and current.get("apply_count") == 0
                    and current.get("identity") is None
                ):
                    self.git(
                        config,
                        "tag",
                        "-f",
                        "-a",
                        config.release_tag,
                        "-m",
                        f"{config.release_tag} rollback after {config.candidate_id} identity interruption",
                        config.prior_tag_target,
                    )
            except Exception as rollback_exc:
                raise OwnerBlocked(
                    "release identity apply failed and prior tag target could not be restored: "
                    f"{type(exc).__name__}: {exc}; rollback={type(rollback_exc).__name__}: {rollback_exc}"
                ) from exc
            raise
        kernel = status.get("identity", {})
        if status.get("valid") is not True or not isinstance(kernel, dict):
            raise OwnerBlocked("release identity apply failed")
        return self.receipt(
            config,
            "identity",
            {
                "schema_version": "px.single-identity-transition-receipt/1.0",
                "campaign_id": config.candidate_id,
                "commit": head,
                "commit_created": False,
                "source_path_count": 0,
                "annotated_tag": config.release_tag,
                "tag_target": head,
                "release_identity_sha256": kernel.get("release_identity_sha256"),
                "source_product_digest": kernel.get("source_product_digest"),
                "source_harness_digest": kernel.get("source_harness_digest"),
                "artifact": {
                    "path": config.relative(config.artifact),
                    "sha256": config.artifact_sha256,
                    "size": config.artifact_size,
                },
                "retag_count": 1,
                "valid": True,
            },
        )

    def package_audit(self, config: Config, claim: Mapping[str, Any]) -> dict[str, Any]:
        from runtime.archive_io import read_archive_bytes, validated_zip

        image = read_archive_bytes(config.artifact)
        before = (
            hashlib.sha256(image).hexdigest(),
            len(image),
            config.artifact.stat().st_mtime_ns,
        )
        # Validate directory, portable identities, compression and byte budgets
        # before any member is expanded for CRC verification.
        with validated_zip(image) as (archive, rows):
            names = [row.filename for row in rows]
            bad_crc = archive.testzip()
        unsafe = [
            name
            for name in names
            if PurePosixPath(name).is_absolute()
            or ".." in PurePosixPath(name).parts
            or "\\" in name
        ]
        links = [
            row.filename
            for row in rows
            if ((row.external_attr >> 16) & 0o170000) == 0o120000
        ]
        encrypted = [row.filename for row in rows if row.flag_bits & 1]
        after = (
            sha256(config.artifact),
            config.artifact.stat().st_size,
            config.artifact.stat().st_mtime_ns,
        )
        valid = (
            before
            == after
            == (config.artifact_sha256, config.artifact_size, config.artifact_mtime_ns)
            and len(rows) == config.zip_entry_count
            and len(names) == len(set(names))
            and bad_crc is None
            and not unsafe
            and not links
            and not encrypted
        )
        kernel = release(config)["identity"]
        return {
            "schema_version": "px.release-stage-evidence/1.0",
            "campaign_id": config.candidate_id,
            "release_identity_sha256": kernel["release_identity_sha256"],
            "source_product_digest": kernel["source_product_digest"],
            "source_harness_digest": kernel["source_harness_digest"],
            "stage": "package",
            "status": "passed" if valid else "failed",
            "claim_id": claim["claim_id"],
            "attempt_count": 1,
            "artifact": {
                "path": config.relative(config.artifact),
                "sha256": config.artifact_sha256,
                "size": config.artifact_size,
            },
            "artifact_mtime_ns": config.artifact_mtime_ns,
            "entry_count": len(rows),
            "unique_entry_count": len(set(names)),
            "crc_clean": bad_crc is None,
            "unsafe_path_count": len(unsafe),
            "encrypted_count": len(encrypted),
            "symlink_count": len(links),
            "artifact_unchanged": before == after,
            "artifact_rebuilt": False,
            "artifact_touched": False,
            "resource_count": 0,
            "active_processes": 0,
            "cleanup_failures": 0,
            "valid": valid,
        }

    def tree(self, root: Path) -> tuple[dict[str, Path], list[str], str]:
        from runtime.archive_io import DEFAULT_LIMITS, reject_path_links, portable_member_name
        from runtime.json_io import read_bounded_bytes
        reject_path_links(root)
        if not root.is_dir():
            raise OwnerBlocked("installed extension tree is unavailable")
        files: dict[str, Path] = {}
        links: list[str] = []
        pending = [root]
        entries = 0
        identities = set()
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as children:
                for child in children:
                    entries += 1
                    if entries > DEFAULT_LIMITS.max_members + 2048:
                        raise OwnerBlocked("installed tree entry budget exceeded")
                    path = Path(child.path)
                    relative = path.relative_to(root).as_posix()
                    portable_member_name(relative, allow_directory=False)
                    identity = relative.casefold()
                    if identity in identities:
                        raise OwnerBlocked("installed tree has a portable path alias")
                    identities.add(identity)
                    info = child.stat(follow_symlinks=False)
                    if child.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                        links.append(relative)
                    elif stat.S_ISDIR(info.st_mode):
                        pending.append(path)
                    elif stat.S_ISREG(info.st_mode):
                        if len(files) >= DEFAULT_LIMITS.max_members:
                            raise OwnerBlocked("installed file count budget exceeded")
                        files[relative] = path
                    else:
                        raise OwnerBlocked("installed tree contains an unsupported filesystem entry")
        digest = hashlib.sha256()
        total = 0
        for relative in sorted(files):
            reject_path_links(files[relative])
            payload = read_bounded_bytes(files[relative], max_bytes=DEFAULT_LIMITS.max_member_bytes)
            total += len(payload)
            if total > DEFAULT_LIMITS.max_expanded_bytes:
                raise OwnerBlocked("installed tree expanded byte budget exceeded")
            for part in (relative.encode(), b"\0", str(len(payload)).encode(), b"\0", hashlib.sha256(payload).digest()):
                digest.update(part)
        return files, sorted(links), digest.hexdigest()

    def list_installed_extensions(
        self, config: Config
    ) -> subprocess.CompletedProcess[str]:
        """Query the exact extension root without inheriting an IDE host profile."""

        if config.identity_kind == "standalone_current_campaign":
            from runtime.json_io import read_bounded_bytes
            command = vscode_cli_argv(config, "--user-data-dir", str(private_installation_root(config) / "user-data"),
                "--extensions-dir", str(config.installed_dir.parent), "--list-extensions", "--show-versions")
            receipt = self.command(config, "install-list", command, timeout_seconds=60)
            text = bytes(read_bounded_bytes(config.root / receipt["path"], max_bytes=2 * 1024 * 1024)).decode("utf-8")
            return subprocess.CompletedProcess(command, 0, text, "")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("VSCODE_")
        }
        with tempfile.TemporaryDirectory(
            prefix="pacify-x-vscode-cli-audit-"
        ) as user_data_dir:
            return subprocess.run(
                [
                    str(config.code_command),
                    "--user-data-dir",
                    user_data_dir,
                    "--extensions-dir",
                    str(config.installed_dir.parent),
                    "--list-extensions",
                    "--show-versions",
                ],
                cwd=config.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
                env=environment,
            )

    def install_audit(self, config: Config, claim: Mapping[str, Any]) -> dict[str, Any]:
        from runtime.archive_io import read_archive_bytes, validated_zip, DEFAULT_LIMITS, reject_path_links
        from runtime.json_io import read_bounded_bytes
        before_files, before_links, before_digest = self.tree(config.installed_dir)
        listed = self.list_installed_extensions(config)
        with validated_zip(read_archive_bytes(config.artifact)) as (archive, _):
            entries = {
                row.filename.removeprefix("extension/"): row
                for row in archive.infolist()
                if not row.is_dir() and row.filename.startswith("extension/")
            }
            entries[".vsixmanifest"] = archive.getinfo("extension.vsixmanifest")
            bad_crc = archive.testzip()
            missing = sorted(set(entries) - set(before_files))
            extra = sorted(set(before_files) - set(entries))
            mismatches: list[str] = []
            identical = 0
            normalized = 0
            for relative in sorted(set(entries) & set(before_files)):
                expected = archive.read(entries[relative])
                reject_path_links(before_files[relative])
                observed = bytes(read_bounded_bytes(before_files[relative], max_bytes=DEFAULT_LIMITS.max_member_bytes))
                if expected == observed:
                    identical += 1
                elif relative == "package.json":
                    expected_json = json.loads(expected)
                    observed_json = json.loads(observed)
                    observed_json.pop("__metadata", None)
                    if expected_json == observed_json:
                        normalized += 1
                    else:
                        mismatches.append(relative)
                else:
                    mismatches.append(relative)
        _, after_links, after_digest = self.tree(config.installed_dir)
        extension_id = (extension_identity(config)["extension_id"]
                        if config.identity_kind == "standalone_current_campaign"
                        else "mountain-nomad-bc.pacify-x-vscode")
        owned = sorted(line.strip() for line in listed.stdout.splitlines()
                       if line.strip().lower().startswith(extension_id + "@"))
        valid = (
            listed.returncode == 0
            and owned
            == [f"{extension_id}@{config.installed_version}"]
            and len(entries) == config.installable_entry_count
            and not missing
            and not extra
            and not mismatches
            and (normalized in (0, 1) if config.identity_kind == "standalone_current_campaign" else normalized == 1)
            and identical + normalized == len(entries)
            and bad_crc is None
            and not before_links
            and not after_links
            and before_digest == after_digest == config.installed_tree_digest
        )
        kernel = release(config)["identity"]
        return {
            "schema_version": "px.install-audit-denominator/1.0",
            "campaign_id": config.candidate_id,
            "release_identity_sha256": kernel["release_identity_sha256"],
            "source_product_digest": kernel["source_product_digest"],
            "source_harness_digest": kernel["source_harness_digest"],
            "claim_id": claim["claim_id"],
            "install_claim_id": claim["claim_id"],
            "artifact": {
                "path": config.relative(config.artifact),
                "sha256": config.artifact_sha256,
                "size": config.artifact_size,
            },
            "listed_owned_versions": owned,
            "exact_version_count": len(owned),
            "installable_entry_count": len(entries),
            "installed_file_count": len(before_files),
            "verified_byte_identical_entries": identical,
            "normalized_package_json_entries": normalized,
            "missing": missing,
            "extra": extra,
            "mismatches": mismatches,
            "crc_failures": [] if bad_crc is None else [bad_crc],
            "installed_symlinks_before": before_links,
            "installed_symlinks_after": after_links,
            "tree_digest_before": before_digest,
            "tree_digest_after": after_digest,
            "installed_tree_unchanged": before_digest == after_digest,
            "machine_mutated": False,
            "install_command_executed": False,
            "release_stage": "passed" if valid else "failed",
            "processing_phase": "installed" if valid else "packaged",
            "resource_count": 0,
            "active_processes": 0,
            "cleanup_failures": 0,
            "audit_valid": valid,
            "valid": valid,
        }

    def execute(self, step: str, config: Config) -> Mapping[str, Any]:
        if config.identity_kind == "standalone_current_campaign" and step in {"package", "install"}:
            return self.current_realization(config, step)
        from runtime.release_campaign import (
            claim_release_stage,
            finish_release_stage,
            supersede_consumed_cleared_release_campaign,
            supersede_failed_release_campaign,
            supersede_invalid_active_release_campaign,
            supersede_invalid_release_identity,
            rewind_failed_release_campaign_repair,
            rewind_consumed_cleared_release_campaign_repair,
            rewind_invalid_active_release_campaign_repair,
            rewind_invalid_release_identity_reconciliation,
        )

        stale: list[str] = []
        if step == "identity":
            identity_manifest(config)
        if step == "sections":
            from runtime.test_profiles import (
                section_status,
                stale_section_execution_order,
            )

            stale = stale_section_execution_order(section_status(config.root))
        if step == "package" and self.package_audit(
            config, {"claim_id": "preclaim-audit"}
        ).get("valid") is not True:
            raise OwnerBlocked("package inputs fail the exact pre-claim audit")
        if step == "install" and self.install_audit(
            config, {"claim_id": "preclaim-audit"}
        ).get("valid") is not True:
            raise OwnerBlocked("install inputs fail the exact pre-claim audit")
        receipt_path = config.evidence_dir / f"{config.candidate_id}-{step}.json"
        outputs = [receipt_path]
        if step in {"full_profile", "validate", "package", "install"}:
            outputs.append(config.log_dir / f"{config.candidate_id}-{step}.log")
        if step == "sections":
            outputs.extend(
                config.log_dir / f"{config.candidate_id}-sections-{name}.log"
                for name in stale
            )
        for output in outputs:
            self.probe_output(output)
        atomic_json(
            receipt_path,
            {
                "schema_version": "px.release-stage-owner-terminal-marker/1.0",
                "candidate_id": config.candidate_id,
                "step": step,
                "status": "running",
                "valid": False,
                "owner_pid": os.getpid(),
                "parent_pid": os.getppid(),
                "host_id": socket.gethostname(),
                "started_at": _now(),
                "attempt_id": uuid4().hex,
                "retry_policy": "no-replay; inspect canonical state",
            },
        )
        if step == "archive_clear":
            current = release(config)
            if already_established_successor(config, current):
                return self.receipt(
                    config,
                    step,
                    {
                        "schema_version": "px.release-successor-receipt/1.0",
                        "candidate_id": config.candidate_id,
                        "archive": current.get("supersedes", {}).get("archive"),
                        "already_established": True,
                        "valid": True,
                    },
                )
            if current.get("state") == "failed":
                if repair(config).get("phase") != "repair_frozen":
                    rewind_failed_release_campaign_repair(config.root)
                status = supersede_failed_release_campaign(
                    config.root,
                    campaign_id=config.candidate_id,
                    reason=(
                        f"{config.predecessor_id} is terminal and the repair campaign is frozen; "
                        f"establish {config.candidate_id} once."
                    ),
                )
            elif current.get("state") == "active":
                stages = current.get("stages", {})
                retained_passes = any(
                    isinstance(stages.get(name), dict)
                    and stages[name].get("status") == "passed"
                    for name in STAGES
                )
                if retained_passes:
                    if repair(config).get("phase") != "repair_frozen":
                        rewind_invalid_active_release_campaign_repair(config.root)
                    status = supersede_invalid_active_release_campaign(
                        config.root,
                        campaign_id=config.candidate_id,
                        reason=(
                            f"{config.predecessor_id} is source-invalid with retained "
                            f"passed stages; establish {config.candidate_id} once."
                        ),
                    )
                else:
                    if repair(config).get("phase") == "revision_reconciled":
                        rewind_invalid_release_identity_reconciliation(config.root)
                    status = supersede_invalid_release_identity(
                        config.root,
                        campaign_id=config.candidate_id,
                        reason=(
                            f"{config.predecessor_id} has one unused invalid identity; "
                            f"establish {config.candidate_id} once."
                        ),
                    )
            else:
                if repair(config).get("phase") == "revision_reconciled":
                    rewind_consumed_cleared_release_campaign_repair(config.root)
                status = supersede_consumed_cleared_release_campaign(
                    config.root,
                    campaign_id=config.candidate_id,
                    reason=(
                        f"{config.predecessor_id} was consumed by a failed pre-identity "
                        f"owner postcondition; establish {config.candidate_id} once."
                    ),
                )
            return self.receipt(
                config,
                step,
                {
                    "schema_version": "px.release-successor-receipt/1.0",
                    "candidate_id": config.candidate_id,
                    "archive": status.get("superseded_archive"),
                    "valid": status.get("valid") is True,
                },
            )
        if step == "reconcile":
            from runtime.generated_artifacts import validate_generated_artifacts
            from runtime.release_artifacts import classify_tree

            generated = validate_generated_artifacts(config.root)
            classification = classify_tree(config.root)
            if (
                generated.get("valid") is not True
                or classification.get("valid") is not True
                or classification.get("product_valid") is not True
            ):
                raise OwnerBlocked("reconciliation post-audit failed")
            self.advance(config, *PHASES[step])
            return self.receipt(
                config,
                step,
                {
                    "schema_version": "px.revision-reconciliation-receipt/1.0",
                    "campaign_id": config.candidate_id,
                    "product_digest": classification.get("product_digest"),
                    "harness_digest": classification.get("harness_digest"),
                    "generated_check_count": generated.get("check_count"),
                    "valid": True,
                },
            )
        if step == "identity":
            return self.identity(config)
        if step == "sections":
            from runtime.test_profiles import (
                governed_section_timeout_envelope,
                section_status,
            )

            claim = claim_release_stage(config.root, "sections")
            finished = False
            try:
                timeout_envelope = governed_section_timeout_envelope(config.root)
                logs = [
                    self.command(
                        config,
                        f"sections-{name}",
                        [
                            sys.executable,
                            "-B",
                            "-m",
                            "runtime.cli",
                            "test-section",
                            "run",
                            name,
                        ],
                        timeout_seconds=timeout_envelope[name],
                    )
                    for name in stale
                ]
                section_evidence = required_section_evidence(section_status(config.root))
                passed = section_evidence["all_required_sections_current"]
                finish_release_stage(
                    config.root,
                    stage="sections",
                    claim_id=str(claim["claim_id"]),
                    passed=passed,
                )
                finished = True
                if not passed:
                    raise OwnerBlocked("not all required governed sections are current")
            except BaseException:
                if not finished:
                    try:
                        finish_release_stage(
                            config.root,
                            stage="sections",
                            claim_id=str(claim["claim_id"]),
                            passed=False,
                        )
                    except Exception:
                        pass
                raise
            self.advance(config, *PHASES[step])
            return self.receipt(
                config,
                step,
                {
                    "schema_version": "px.governed-sections-complete-denominator/1.0",
                    "campaign_id": config.candidate_id,
                    "claim_id": claim["claim_id"],
                    "stale_sections_before": stale,
                    "owners": logs,
                    **section_evidence,
                    "valid": True,
                },
            )
        if step in {"full_profile", "validate"}:
            from runtime.test_profiles import governed_full_profile_timeout_envelope

            action = (
                ["test-profile", "run", "full"]
                if step == "full_profile"
                else ["validate"]
            )
            log = self.command(
                config,
                step,
                [sys.executable, "-B", "-m", "runtime.cli", *action],
                timeout_seconds=(
                    governed_full_profile_timeout_envelope(config.root)[
                        "__profile_owner__"
                    ]
                    if step == "full_profile"
                    else 1800
                ),
            )
            current = release(config)
            kernel = current.get("identity", {})
            if current.get("stages", {}).get(step, {}).get(
                "status"
            ) != "passed" or not isinstance(kernel, dict):
                raise OwnerBlocked(f"canonical {step} CLI did not pass")
            self.advance(config, *PHASES[step])
            return self.receipt(
                config,
                step,
                {
                    "schema_version": "px.full-profile-receipt/1.0"
                    if step == "full_profile"
                    else "px.validation-receipt/1.0",
                    "campaign_id": config.candidate_id,
                    "release_identity_sha256": kernel.get("release_identity_sha256"),
                    "owner_invocations": 1,
                    "owner_log": log,
                    "stage_status": "passed",
                    "valid": True,
                },
            )
        claim = claim_release_stage(config.root, step)
        finished = False
        try:
            payload = (
                self.package_audit(config, claim)
                if step == "package"
                else self.install_audit(config, claim)
            )
            audit_log = config.log_dir / f"{config.candidate_id}-{step}.log"
            atomic_json(audit_log, payload)
            payload.update(
                audit_log=config.relative(audit_log),
                audit_log_sha256=sha256(audit_log),
            )
            passed = payload.get("valid") is True
            finish_release_stage(
                config.root, stage=step, claim_id=str(claim["claim_id"]), passed=passed
            )
            finished = True
            receipt = self.receipt(config, step, payload)
            if not passed:
                raise OwnerBlocked(f"{step} audit failed")
        except BaseException:
            if not finished:
                try:
                    finish_release_stage(
                        config.root,
                        stage=step,
                        claim_id=str(claim["claim_id"]),
                        passed=False,
                    )
                except Exception:
                    pass
            raise
        self.advance(config, *PHASES[step])
        return receipt

    def verify(self, step: str, config: Config) -> None:
        if config.identity_kind == "standalone_current_campaign" and step in {"package", "install"}:
            config = observe_completed_stages(config)
        current_release = release(config)
        current_repair = repair(config)
        if step == "archive_clear":
            valid = (
                current_release.get("campaign_id") == config.candidate_id
                and current_release.get("state") == "cleared"
                and current_release.get("apply_count") == 0
                and current_release.get("identity") is None
                and current_release.get("active_claim") is None
                and tuple(current_release.get("stages", {})) == STAGES
                and all(
                    row.get("status") == "pending"
                    for row in current_release["stages"].values()
                )
            )
        elif step == "reconcile":
            valid = (
                current_release.get("state") == "cleared"
                and current_repair.get("phase") == "revision_reconciled"
            )
        elif step == "identity":
            valid = (
                current_release.get("state") == "active"
                and current_release.get("apply_count") == 1
                and isinstance(current_release.get("identity"), dict)
            )
        else:
            valid = (
                current_release.get("stages", {}).get(step, {}).get("status")
                == "passed"
                and current_repair.get("phase") == PHASES[step][1]
            )
        receipt_path = config.evidence_dir / f"{config.candidate_id}-{step}.json"
        receipt = load_object(receipt_path) if receipt_path.is_file() else {}
        expected_schema = STAGE_RECEIPT_SCHEMAS[step]
        receipt_campaign = receipt.get(STAGE_RECEIPT_CANDIDATE_FIELDS[step])
        receipt_valid = (
            receipt.get("schema_version") == expected_schema
            and receipt_campaign == config.candidate_id
            and receipt.get("valid") is True
        )
        if step == "sections":
            from runtime.test_profiles import section_status
            expected_sections = required_section_evidence(section_status(config.root))
            receipt_valid = receipt_valid and all(
                receipt.get(key) == value for key, value in expected_sections.items()
            )
        if step in {"sections", "package", "install"}:
            expected_claim = current_release.get("stages", {}).get(step, {}).get("claim_id")
            actual_claim = receipt.get("claim_id")
            if step == "install" and actual_claim is None:
                actual_claim = receipt.get("install_claim_id")
            receipt_valid = receipt_valid and actual_claim == expected_claim
        if step == "identity" and config.identity_kind == "standalone_current_campaign":
            from runtime.release_source_identity import verify_release_source_identity

            source = receipt.get("source_identity")
            source_valid = verify_release_source_identity(config.root, source).get("valid") is True
            kernel = current_release.get("identity", {})
            receipt_valid = (
                receipt_valid
                and source_valid
                and isinstance(source, dict)
                and source.get("source_freeze") == config.source_freeze_reference
                and source.get("campaign_id") == config.candidate_id
                and all(receipt.get(key) == kernel.get(key) for key in (
                    "release_identity_sha256", "source_product_digest", "source_harness_digest"))
                and receipt.get("git_acceptance") == {"state": "deferred_by_owner", "satisfied": False}
                and receipt.get("commit_created") is False
                and type(receipt.get("retag_count")) is int
                and receipt["retag_count"] == 0
                and receipt.get("artifact") == {
                    "state": "planned", "path": config.relative(config.artifact),
                    "type": config.artifact_type, "build_owner": config.artifact_build_owner,
                }
            )
        elif step in {"identity", "package", "install"}:
            artifact = receipt.get("artifact")
            receipt_valid = receipt_valid and artifact == {
                "path": config.relative(config.artifact),
                "sha256": config.artifact_sha256,
                "size": config.artifact_size,
            }
        if step in {"full_profile", "validate", "package", "install"}:
            identity = current_release.get("identity", {})
            receipt_valid = (
                receipt_valid
                and isinstance(identity, dict)
                and receipt.get("release_identity_sha256")
                == identity.get("release_identity_sha256")
            )
            if step in {"package", "install"}:
                receipt_valid = receipt_valid and all(
                    receipt.get(key) == identity.get(key)
                    for key in ("source_product_digest", "source_harness_digest")
                )
        resources = resource_postcondition(config)
        clean = resources.get("valid") is True
        if (
            not valid
            or not clean
            or not receipt_path.is_file()
            or receipt_path.is_symlink()
            or not receipt_valid
        ):
            details = {
                "state_valid": valid,
                "resource_valid": clean,
                "receipt_exists": receipt_path.is_file(),
                "receipt_is_link": receipt_path.is_symlink(),
                "receipt_valid": receipt_valid,
            }
            raise OwnerBlocked(
                f"{step} postcondition is not exact: "
                + json.dumps(details, sort_keys=True, separators=(",", ":"))
            )


def already_established_successor(config: "Config", current_release: dict) -> bool:
    """True when the release campaign already IS this config's governed successor.

    One pre-identity owner failure can leave a candidate established by an exact
    archived supersession (hash-verified, still cleared and unused). Replaying the
    supersession is forbidden, so archive_clear must verify this shape instead.
    """

    supersedes = current_release.get("supersedes") or {}
    archive_rel = supersedes.get("archive")
    predecessor = getattr(config, "predecessor_id", None) or getattr(
        config, "predecessor_campaign_id", None
    )
    return (
        current_release.get("campaign_id") == config.candidate_id
        and current_release.get("state") == "cleared"
        and current_release.get("apply_count") == 0
        and current_release.get("identity") is None
        and current_release.get("active_claim") is None
        and tuple(current_release.get("stages", {})) == STAGES
        and all(
            row.get("status") == "pending"
            for row in current_release.get("stages", {}).values()
        )
        and supersedes.get("campaign_id") == predecessor
        and isinstance(archive_rel, str)
        and bool(archive_rel)
        and _valid_supersession_archive(config.root, archive_rel)
        and supersedes.get("archive_sha256") == _archive_binding(config.root, archive_rel)
    )


def _archive_binding(root: Path, archive_rel: str) -> str:
    """Canonical sha of a supersession archive, matching release-campaign _sha."""

    import json as _json

    from runtime.release_campaign import _sha

    archive = _json.loads((root / archive_rel).read_text(encoding="utf-8"))
    archive.pop("archive_sha256", None)
    return _sha(archive)


def _valid_supersession_archive(root: Path, archive_rel: str) -> bool:
    import json as _json

    from runtime.release_campaign import _valid_pre_identity_failure

    path = root / archive_rel
    if not path.is_file() or path.is_symlink():
        return False
    archive = _json.loads(path.read_text(encoding="utf-8"))
    state = archive.get("campaign_state") or {}
    if state.get("pre_identity_reconciliation_successor") is True:
        return _valid_pre_identity_failure(
            state.get("pre_identity_failure"), str(state.get("campaign_id"))
        )
    return True


def run(config: Config, step: str, effects: Effects) -> dict[str, Any]:
    readiness = check(config, step)
    if readiness["valid"] is not True:
        raise OwnerNotAdmitted("; ".join(readiness["errors"]))
    evidence = dict(effects.execute(step, config))
    effects.verify(step, config)
    return {
        "schema_version": "px.release-stage-owner-result/1.0",
        "candidate_id": config.candidate_id,
        "step": step,
        "one_step": True,
        "valid": True,
        "evidence": evidence,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--step", choices=STEPS, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    config: Config | None = None
    try:
        config = Config.load(args.config)
        if not args.check and not args.execute:
            output = plan(config, args.step)
        elif args.check:
            output = check(config, args.step)
        else:
            output = run(config, args.step, ProductionEffects())
        print(json.dumps(output, indent=2))
        return 0 if output.get("valid") else 1
    except (OwnerBlocked, OSError, ValueError, json.JSONDecodeError) as exc:
        marker_error: Exception | None = None
        if (
            args.execute
            and config is not None
            and not isinstance(exc, OwnerNotAdmitted)
            and args.step in {"archive_clear", "reconcile", "identity"}
        ):
            try:
                current = release(config)
                if (
                    current.get("campaign_id") == config.candidate_id
                    and current.get("state") == "cleared"
                ):
                    from runtime.release_campaign import mark_pre_identity_owner_failure

                    mark_pre_identity_owner_failure(
                        config.root,
                        campaign_id=config.candidate_id,
                        owner=args.step,
                        error=f"{type(exc).__name__}: {exc}",
                    )
            except (OSError, ValueError, json.JSONDecodeError) as marker_exc:
                marker_error = marker_exc
        errors = [f"{type(exc).__name__}: {exc}"]
        if marker_error is not None:
            errors.append(
                "pre-identity failure marker could not be recorded: "
                f"{type(marker_error).__name__}: {marker_error}"
            )
        print(
            json.dumps({"valid": False, "errors": errors}, indent=2)
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
