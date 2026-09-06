"""Plan, check, or execute exactly one parameterized release-stage owner."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from typing import Any, Mapping, Protocol
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "px.release-stage-owner-config/1.0"
STEPS = (
    "archive_clear",
    "reconcile",
    "identity",
    "sections",
    "full_profile",
    "validate",
    "package",
    "install",
)
PHASES = {
    "archive_clear": ("repair_frozen", "repair_frozen"),
    "reconcile": ("repair_frozen", "revision_reconciled"),
    "identity": ("revision_reconciled", "revision_reconciled"),
    "sections": ("revision_reconciled", "sections_current"),
    "full_profile": ("sections_current", "full_profile_passed"),
    "validate": ("full_profile_passed", "validated"),
    "package": ("validated", "packaged"),
    "install": ("packaged", "installed"),
}
STAGES = (
    "sections",
    "full_profile",
    "validate",
    "package",
    "install",
    "installed_operational",
    "certify",
)
STAGE_PHASES = {
    "sections": "revision_reconciled",
    "full_profile": "sections_current",
    "validate": "full_profile_passed",
    "package": "validated",
    "install": "packaged",
    "installed_operational": "installed",
    "certify": "installed_operational",
}


class OwnerBlocked(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
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

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = load_object(path)
        if raw.get("schema_version") != SCHEMA:
            raise OwnerBlocked(f"config must use {SCHEMA}")
        root_raw = Path(str(raw.get("root") or ""))
        root = (
            root_raw if root_raw.is_absolute() else path.parent / root_raw
        ).resolve()
        artifact = raw.get("artifact")
        identity = raw.get("identity")
        install = raw.get("install")
        if (
            not isinstance(artifact, dict)
            or not isinstance(identity, dict)
            or not isinstance(install, dict)
        ):
            raise OwnerBlocked("artifact, identity, and install objects are required")
        candidate = str(raw.get("candidate_id") or "").strip()
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
            path_manifest=inside(root, identity.get("path_manifest"), "path_manifest"),
            commit_message=str(identity.get("commit_message") or "").strip(),
            release_tag=str(identity.get("release_tag") or "").strip(),
            prior_tag_target=str(identity.get("prior_tag_target") or "").strip(),
            zip_entry_count=int(artifact.get("entry_count") or 0),
            installed_dir=Path(str(install.get("directory") or "")).resolve(),
            code_command=Path(str(install.get("code_command") or "")).resolve(),
            installed_tree_digest=str(install.get("tree_digest") or ""),
            installed_version=str(install.get("version") or "").strip(),
            installable_entry_count=int(install.get("entry_count") or 0),
        )
        if (
            not candidate
            or not predecessor
            or candidate == predecessor
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or result.artifact_size <= 0
            or result.artifact_mtime_ns <= 0
            or result.zip_entry_count <= 0
            or result.installable_entry_count <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", result.installed_tree_digest)
            or not result.installed_version
            or not result.commit_message
            or not result.release_tag.startswith("v")
            or len(result.prior_tag_target) != 40
        ):
            raise OwnerBlocked("config contains an incomplete exact owner contract")
        return result

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def release(config: Config) -> dict[str, Any]:
    return load_object(
        config.root / ".engineering-bootstrap/processing-order/release-identity.json"
    )


def repair(config: Config) -> dict[str, Any]:
    return load_object(
        config.root / ".engineering-bootstrap/processing-order/repair-campaign.json"
    )


def resource_postcondition(config: Config) -> dict[str, Any]:
    """Allow only this supervised child while it is proving its own effects."""

    from runtime.resource_lifecycle import resource_status

    ledger_path = config.root / ".engineering-bootstrap/resource-lifecycle/ledger.json"
    status = resource_status(ledger_path)
    ledger = load_object(ledger_path)
    active = [
        row
        for row in ledger.get("resources", ())
        if isinstance(row, dict) and row.get("active") is True
    ]
    exact_self = (
        len(active) == 1
        and active[0].get("resource_type") == "process"
        and active[0].get("pid") == os.getpid()
        and active[0].get("run_id") == config.candidate_id
        and active[0].get("creator") == "scripts.run_release_candidate"
    )
    valid = (
        status.get("valid") is True
        and status.get("reclaimable_paths") == 0
        and status.get("cleanup_failures") == 0
        and (status.get("active_processes") == 0 or exact_self)
    )
    return {**status, "active_records": len(active), "exact_supervised_self": exact_self, "valid": valid}


def check(config: Config, step: str) -> dict[str, Any]:
    errors: list[str] = []
    if step not in STEPS:
        errors.append("unsupported step")
    if not config.artifact.is_file() or config.artifact.is_symlink():
        errors.append("artifact is not a regular file")
    else:
        info = config.artifact.stat()
        if (sha256(config.artifact), info.st_size, info.st_mtime_ns) != (
            config.artifact_sha256,
            config.artifact_size,
            config.artifact_mtime_ns,
        ):
            errors.append("artifact identity differs from config")
    try:
        current_repair = repair(config)
        current_release = release(config)
        archive_recovery_phase = None
        if step == "archive_clear" and current_release.get("state") == "failed":
            failed_stages = [
                name
                for name, record in current_release.get("stages", {}).items()
                if isinstance(record, dict) and record.get("status") == "failed"
            ]
            if len(failed_stages) == 1 and failed_stages[0] in STAGE_PHASES:
                archive_recovery_phase = STAGE_PHASES[failed_stages[0]]
        elif step == "archive_clear" and current_release.get("state") == "active":
            archive_recovery_phase = "revision_reconciled"
        repair_phase_valid = current_repair.get("phase") == PHASES.get(
            step, (None,)
        )[0] or current_repair.get("phase") == archive_recovery_phase
        if (
            current_repair.get("campaign_id")
            != "pacify-x-cohesion-closure-repair12-20260905"
            or not repair_phase_valid
            or current_repair.get("intake_open") is not False
            or current_repair.get("unresolved") != []
        ):
            errors.append(f"repair12 phase is not exact for {step}")
        if step == "archive_clear":
            unused_invalid_identity = False
            if (
                current_release.get("state") == "active"
                and current_release.get("apply_count") == 1
                and isinstance(current_release.get("identity"), dict)
                and current_release.get("active_claim") is None
                and tuple(current_release.get("stages", {})) == STAGES
                and all(
                    isinstance(record, dict) and record.get("status") == "pending"
                    for record in current_release.get("stages", {}).values()
                )
            ):
                from runtime.release_campaign import release_campaign_status

                verification = release_campaign_status(config.root, verify_source=True)
                unused_invalid_identity = (
                    verification.get("valid") is False
                    and bool(verification.get("errors"))
                )
            if (
                current_release.get("campaign_id") != config.predecessor_id
                or current_release.get("active_claim") is not None
                or current_release.get("state") not in {"failed", "cleared", "active"}
                or (
                    current_release.get("state") == "cleared"
                    and (
                        current_release.get("apply_count") != 0
                        or current_release.get("identity") is not None
                    )
                )
                or (
                    current_release.get("state") == "active"
                    and not unused_invalid_identity
                )
            ):
                errors.append(
                    "archive_clear requires a terminal failed, unused cleared, "
                    "or unused invalid-identity predecessor"
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
    if (config.evidence_dir / f"{config.candidate_id}-{step}.json").exists() or (
        config.log_dir / f"{config.candidate_id}-{step}.log"
    ).exists():
        errors.append("fresh owner receipt already exists")
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
        "candidate_id": config.candidate_id,
        "step": step,
        "phase_before": PHASES.get(step, (None, None))[0],
        "phase_after": PHASES.get(step, (None, None))[1],
    }


class Effects(Protocol):
    def execute(self, step: str, config: Config) -> Mapping[str, Any]: ...
    def verify(self, step: str, config: Config) -> None: ...


class ProductionEffects:
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
        path = (
            config.root / ".engineering-bootstrap/processing-order/repair-campaign.json"
        )
        value = load_object(path)
        if (
            value.get("phase") != before
            or value.get("intake_open") is not False
            or value.get("unresolved") != []
        ):
            raise OwnerBlocked(f"repair phase cannot advance {before} -> {after}")
        value["phase"] = after
        atomic_json(path, value)

    def command(self, config: Config, name: str, argv: list[str]) -> dict[str, Any]:
        config.log_dir.mkdir(parents=True, exist_ok=True)
        log = config.log_dir / f"{config.candidate_id}-{name}.log"
        with log.open("x", encoding="utf-8", newline="\n") as stream:
            result = subprocess.run(
                argv,
                cwd=config.root,
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        if result.returncode:
            raise OwnerBlocked(f"{name} exited {result.returncode}")
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

    def identity(self, config: Config) -> Mapping[str, Any]:
        from runtime.release_campaign import apply_release_identity
        from runtime.release_identity import _release_dirty_state, authoritative_version

        manifest = load_object(config.path_manifest)
        paths = manifest.get("paths")
        mutable_paths = manifest.get("mutable_paths", [])
        if (
            not isinstance(paths, list)
            or not paths
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
                "identity manifest source/mutable paths must be sorted, disjoint, and safe"
            )
        dirty = _release_dirty_state(config.root)
        if dirty.get("classifier_errors"):
            raise OwnerBlocked("release source classification is invalid")
        if set(dirty.get("blocking_paths", ())) != set(paths):
            raise OwnerBlocked(
                "blocking source changes differ from the explicit identity manifest"
            )
        if set(dirty.get("mutable_control_paths", ())) != set(mutable_paths):
            raise OwnerBlocked(
                "mutable control changes differ from the explicit identity manifest"
            )
        self.git(config, "add", "--", *paths)
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
        self.git(config, "commit", "-m", config.commit_message)
        head = self.git(config, "rev-parse", "HEAD")
        post_commit = _release_dirty_state(config.root)
        if post_commit.get("blocking_paths") or post_commit.get("classifier_errors"):
            raise OwnerBlocked("source commit left blocking release-input drift")
        self.git(
            config,
            "tag",
            "-f",
            "-a",
            config.release_tag,
            "-m",
            f"{config.release_tag} final100",
            head,
        )
        if self.git(config, "rev-list", "-n", "1", config.release_tag) != head:
            raise OwnerBlocked("authorized one-time retag did not bind HEAD")
        status = apply_release_identity(config.root)
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
        before = (
            sha256(config.artifact),
            config.artifact.stat().st_size,
            config.artifact.stat().st_mtime_ns,
        )
        with zipfile.ZipFile(config.artifact) as archive:
            rows = archive.infolist()
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
        files: dict[str, Path] = {}
        links: list[str] = []
        for current, directories, names in os.walk(
            root, topdown=True, followlinks=False
        ):
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
        return files, sorted(links), digest.hexdigest()

    def install_audit(self, config: Config, claim: Mapping[str, Any]) -> dict[str, Any]:
        before_files, before_links, before_digest = self.tree(config.installed_dir)
        listed = subprocess.run(
            [str(config.code_command), "--list-extensions", "--show-versions"],
            cwd=config.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        with zipfile.ZipFile(config.artifact) as archive:
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
                observed = before_files[relative].read_bytes()
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
        owned = sorted(
            line.strip()
            for line in listed.stdout.splitlines()
            if line.strip().lower().startswith("mountain-nomad-bc.pacify-x-vscode@")
        )
        valid = (
            listed.returncode == 0
            and owned
            == [f"mountain-nomad-bc.pacify-x-vscode@{config.installed_version}"]
            and len(entries) == config.installable_entry_count
            and not missing
            and not extra
            and not mismatches
            and normalized == 1
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
        from runtime.release_campaign import (
            claim_release_stage,
            finish_release_stage,
            supersede_consumed_cleared_release_campaign,
            supersede_failed_release_campaign,
            supersede_invalid_release_identity,
            rewind_failed_release_campaign_repair,
            rewind_invalid_release_identity_reconciliation,
        )

        stale: list[str] = []
        if step == "identity" and (
            not config.path_manifest.is_file() or config.path_manifest.is_symlink()
        ):
            raise OwnerBlocked("identity path manifest is not a regular file")
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
            },
        )
        if step == "archive_clear":
            current = release(config)
            if current.get("state") == "failed":
                if repair(config).get("phase") != "repair_frozen":
                    rewind_failed_release_campaign_repair(config.root)
                status = supersede_failed_release_campaign(
                    config.root,
                    campaign_id=config.candidate_id,
                    reason=(
                        f"{config.predecessor_id} is terminal and repair12 is frozen; "
                        f"establish {config.candidate_id} once."
                    ),
                )
            elif current.get("state") == "active":
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
            from scripts.clean_source_export import _rebuild_candidate_projections

            _rebuild_candidate_projections(config.root)
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
            from runtime.test_profiles import section_status

            claim = claim_release_stage(config.root, "sections")
            finished = False
            try:
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
                    )
                    for name in stale
                ]
                passed = section_status(config.root).get("valid") is True
                finish_release_stage(
                    config.root,
                    stage="sections",
                    claim_id=str(claim["claim_id"]),
                    passed=passed,
                )
                finished = True
                if not passed:
                    raise OwnerBlocked("not all six governed sections are current")
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
                    "all_six_current": True,
                    "valid": True,
                },
            )
        if step in {"full_profile", "validate"}:
            action = (
                ["test-profile", "run", "full"]
                if step == "full_profile"
                else ["validate"]
            )
            log = self.command(
                config, step, [sys.executable, "-B", "-m", "runtime.cli", *action]
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
        expected_schema = {
            "archive_clear": "px.release-successor-receipt/1.0",
            "reconcile": "px.revision-reconciliation-receipt/1.0",
            "identity": "px.single-identity-transition-receipt/1.0",
            "sections": "px.governed-sections-complete-denominator/1.0",
            "full_profile": "px.full-profile-receipt/1.0",
            "validate": "px.validation-receipt/1.0",
            "package": "px.release-stage-evidence/1.0",
            "install": "px.install-audit-denominator/1.0",
        }[step]
        receipt_campaign = receipt.get("candidate_id") if step == "archive_clear" else receipt.get("campaign_id")
        receipt_valid = (
            receipt.get("schema_version") == expected_schema
            and receipt_campaign == config.candidate_id
            and receipt.get("valid") is True
        )
        if step in {"sections", "package", "install"}:
            expected_claim = current_release.get("stages", {}).get(step, {}).get("claim_id")
            actual_claim = receipt.get("claim_id")
            if step == "install" and actual_claim is None:
                actual_claim = receipt.get("install_claim_id")
            receipt_valid = receipt_valid and actual_claim == expected_claim
        if step in {"identity", "package", "install"}:
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
            raise OwnerBlocked(f"{step} postcondition is not exact")


def run(config: Config, step: str, effects: Effects) -> dict[str, Any]:
    readiness = check(config, step)
    if readiness["valid"] is not True:
        raise OwnerBlocked("; ".join(readiness["errors"]))
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
    try:
        config = Config.load(args.config.resolve(strict=True))
        if not args.check and not args.execute:
            output = plan(config, args.step)
        elif args.check:
            output = check(config, args.step)
        else:
            output = run(config, args.step, ProductionEffects())
        print(json.dumps(output, indent=2))
        return 0 if output.get("valid") else 1
    except (OwnerBlocked, OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"valid": False, "errors": [f"{type(exc).__name__}: {exc}"]}, indent=2
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
