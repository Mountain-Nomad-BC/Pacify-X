"""Create a deterministic, non-destructive source handoff archive."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4
import zipfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.repository_scope import is_external_environment_relative  # noqa: E402


EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode-test",
    ".VSCodeCounter",
    "__pycache__",
    "PortableGit",
    "Python",
    "build",
    "dist",
    "evidence",
    "node_modules",
}
MAX_SOURCE_HANDOFF_BYTES = 128 * 1024 * 1024
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}
EXCLUDED_FILES = {
    "evidence/full-unittest-team-fabric-20260810.log",
    "extension/evidence/historical/vscode-host-listener-smoke-0.5.4.json",
    "registry/.operational-gap-ledger.lock",
}
TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".ts",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
RETAINED_CONTROL_STATE = {
    ".engineering-bootstrap/project-management/state.json",
    ".engineering-bootstrap/project-map/architecture-graph.json",
    ".engineering-bootstrap/project-registry.json",
}
RETAINED_CONTROL_TREES = {
    # This two-file authority projection is required to verify the exported
    # commissioning ledger.  The volatile operation bus remains excluded.
    ".engineering-bootstrap/.ledger-authority/commissioning-events",
}


def _mode(data: bytes) -> str:
    return "0755" if data.startswith(b"#!") else "0644"


def _archive_bytes(path: Path, relative: str) -> tuple[bytes, bool]:
    # Export custody is byte-preserving.  Any normalization must happen before
    # ownership/currentness evidence is generated, never during handoff.
    return path.read_bytes(), False


def included_files(root: Path, output: Path | None = None) -> tuple[Path, ...]:
    resolved_output = output.resolve() if output else None
    records = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        retained_test_receipt = (
            len(relative.parts) >= 3
            and relative.parts[0] == ".engineering-bootstrap"
            and relative.parts[1] == "test-evidence"
            and relative.suffix.casefold() == ".json"
        )
        retained_control_state = relative.as_posix() in RETAINED_CONTROL_STATE
        retained_control_tree = any(
            relative.as_posix() == prefix
            or relative.as_posix().startswith(f"{prefix}/")
            for prefix in RETAINED_CONTROL_TREES
        )
        generated_or_dependency_tree = bool(
            EXCLUDED_DIRS.intersection(relative.parts)
        ) or (
            is_external_environment_relative(relative)
            and not retained_test_receipt
            and not retained_control_state
            and not retained_control_tree
        )
        if (
            generated_or_dependency_tree
            or (
                relative.parts
                and relative.parts[0] == ".engineering-bootstrap"
                and not retained_test_receipt
                and not retained_control_state
                and not retained_control_tree
            )
            or not path.is_file()
            or path.is_symlink()
            or path.suffix.casefold() in EXCLUDED_SUFFIXES
            or path.name == "SHA256SUMS.txt"
            or path.name == ".env"
            or path.name.startswith(".env.")
            or relative.as_posix() in EXCLUDED_FILES
            or "preserved-extension-installations" in relative.parts
            or "preserved-skills" in relative.parts
            or (resolved_output is not None and path.resolve() == resolved_output)
        ):
            continue
        records.append(path)
    return tuple(
        sorted(records, key=lambda item: item.relative_to(root).as_posix().casefold())
    )


def _snapshot(
    root: Path, output: Path, artifacts: tuple[Path, ...]
) -> tuple[list[dict[str, object]], list[tuple[str, bytes, str]]]:
    records: list[dict[str, object]] = []
    payloads: list[tuple[str, bytes, str]] = []
    for path in included_files(root, output):
        relative = path.relative_to(root).as_posix()
        source = path.read_bytes()
        data, normalized = _archive_bytes(path, relative)
        mode = _mode(data)
        payloads.append((relative, data, mode))
        records.append(
            {
                "path": relative,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "mode": mode,
                "eol_normalized": normalized,
            }
        )
    artifact_names: set[str] = set()
    for path in artifacts:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or resolved.suffix.casefold() != ".vsix":
            raise ValueError("audit artifact must be an existing VSIX file")
        if resolved.name.casefold() in artifact_names:
            raise ValueError("audit artifact basenames must be unique")
        artifact_names.add(resolved.name.casefold())
        data = resolved.read_bytes()
        relative = f"AUDIT_ARTIFACTS/{resolved.name}"
        payloads.append((relative, data, "0644"))
        records.append(
            {
                "path": relative,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "mode": "0644",
            }
        )
    records.sort(key=lambda item: str(item["path"]).casefold())
    payloads.sort(key=lambda item: item[0].casefold())
    source_bytes = sum(
        len(data)
        for relative, data, _mode_value in payloads
        if not relative.startswith("AUDIT_ARTIFACTS/")
    )
    if source_bytes > MAX_SOURCE_HANDOFF_BYTES:
        raise ValueError(
            "source-only handoff exceeds the 128 MiB product-source budget; "
            "partition generated state or historical evidence before export"
        )
    return records, payloads


def _certification_preflight(
    root: Path, artifacts: tuple[Path, ...]
) -> dict[str, object]:
    from runtime.effect_surface import validate_effect_surfaces
    from runtime.evidence_index import build_index
    from runtime.evidence_portability import validate_evidence_portability
    from runtime.generated_artifacts import validate_generated_artifacts
    from runtime.licensing import validate_licensing
    from runtime.provider_gateway import scan_direct_provider_routes
    from runtime.release_audit import audit_framework
    from runtime.registry import validate_registry
    from runtime.sanitation_assurance import build_sanitation_summary
    from runtime.structural_integrity import audit_structural_integrity
    from runtime.test_profiles import group_status, section_status
    from scripts.audit_sanitization import audit as audit_sanitization
    from scripts.build_completion_status import build as build_completion_status

    try:
        stored_completion = json.loads(
            (root / "registry/completion_status.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        stored_completion = None
    fresh_completion = build_completion_status(root)
    artifact_hashes = [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in artifacts
    ]

    licensing = validate_licensing(root)
    sanitation_excluded_names = frozenset(
        EXCLUDED_DIRS
        | {
            ".engineering-bootstrap",
            "preserved-extension-installations",
            "preserved-skills",
        }
        | {
            path.name
            for path in root.iterdir()
            if path.is_dir() and path.name.startswith(".venv")
        }
    )
    identifier_audit = audit_sanitization(
        root, excluded_names=sanitation_excluded_names
    )
    checks = {
        "canonical_validate": validate_registry(root),
        "provider_routes": scan_direct_provider_routes(root),
        "test_sections": section_status(root),
        "test_groups": group_status(root),
        "effect_surfaces": validate_effect_surfaces(root),
        "evidence_portability": validate_evidence_portability(root),
        "generated_artifacts": validate_generated_artifacts(root),
        "release_audit": audit_framework(root, require_external_manifests=True),
        "structural_integrity": audit_structural_integrity(root),
        "licensing": licensing,
        "sanitation": build_sanitation_summary(root, identifier_audit, licensing),
        "current_evidence": build_index(root, artifacts=artifacts),
        "completion_projection_identity": {
            "schema_version": "px.completion-projection-identity/1.0",
            "valid": stored_completion == fresh_completion,
        },
        "platform_independent_artifact_identity": {
            "schema_version": "px.platform-independent-vsix-identity/1.0",
            "valid": len(set(artifact_hashes)) <= 1,
            "artifact_count": len(artifact_hashes),
            "distinct_sha256_count": len(set(artifact_hashes)),
        },
    }
    failed = sorted(name for name, result in checks.items() if not result.get("valid"))
    return {
        "schema_version": "px.clean-export-preflight/1.0",
        "valid": not failed,
        "failed": failed,
        "checks": {
            name: {
                "valid": bool(result.get("valid")),
                "schema_version": result.get("schema_version"),
            }
            for name, result in checks.items()
        },
    }


def _write_json(path: Path, value: object, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=sort_keys) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _rebuild_candidate_projections(root: Path) -> None:
    """Rebuild hash-bound projections from the exact final candidate bytes.

    This runs only for a real certification export. It deliberately mutates the
    registered staging candidate before its manifest is computed; neither the
    archive writer nor extracted replay may change a payload byte afterward.
    """
    from runtime.artifact_reachability import build_artifact_reachability
    from runtime.effect_surface import discover_effect_surfaces
    from runtime.evidence_portability import discover_historical_references
    from runtime.exact_tool_certification import certify_exact_tools
    from runtime.engine_identity import write_engine_identity
    from runtime.graph_registry import write_graph_artifacts
    from runtime.python_surface_certification import certify_python_surfaces
    from scripts.build_contract_ownership_registry import (
        build as build_contract_ownership,
    )
    from runtime.build_claims import expected_build_claims, update_readme_claims
    from runtime.provider_gateway import build_provider_route_index
    from scripts.build_declared_suite_template_projections import (
        reconcile as reconcile_templates,
    )
    from scripts.build_domain_tool_projections import reconcile as reconcile_wrappers
    from scripts.build_profile_projections import reconcile as reconcile_profiles
    from scripts.build_python_dependency_ownership import build as build_dependencies
    from scripts.build_registry_envelope_inventory import build_inventory
    from runtime.generated_dependency import generated_dependency_graph
    from runtime.test_profiles import build_test_group_index
    from scripts.reconcile_commissioned_skill_registry import (
        reconcile as reconcile_skills,
    )
    from scripts.reconcile_declared_tool_hashes import expected as declared_tool_outputs

    reconcile_wrappers(root, check=False)
    reconcile_templates(root, check=False)
    reconcile_profiles(root, check=False)
    reconcile_skills(root, check=False)
    for relative, payload in declared_tool_outputs(root).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    write_graph_artifacts(root)
    _write_json(
        root / "registry/contract_ownership.json",
        build_contract_ownership(root),
        sort_keys=False,
    )
    _write_json(
        root / "registry/provider_route_scan.json", build_provider_route_index(root)
    )
    surface = certify_python_surfaces(
        root, certify_exact_tools(root), require_map_current=False
    )
    surface["map_current"] = True
    _write_json(root / "registry/python_surface_ownership.json", surface)
    _write_json(
        root / "registry/python_dependency_ownership.json", build_dependencies(root)
    )
    effects = discover_effect_surfaces(root)
    _write_json(
        root / "registry/effect_surface_ownership.json",
        {
            "schema_version": "1.0",
            "record_count": len(effects),
            "records": effects,
        },
    )
    references = discover_historical_references(root)
    _write_json(
        root / "registry/historical_external_references.json",
        {
            "schema_version": "1.0",
            "reference_count": len(references),
            "records": references,
        },
    )
    claims = expected_build_claims(root)
    _write_json(root / "registry/build_claims.json", claims, sort_keys=False)
    update_readme_claims(root, claims)
    preflight_policy = json.loads(
        (root / "policies/release-preflight.json").read_text(encoding="utf-8")
    )
    _write_json(
        root / "registry/generated_dependency_graph.json",
        generated_dependency_graph(preflight_policy["generated_authorities"]),
    )
    _write_json(root / "registry/registry_envelope_inventory.json", build_inventory())
    _write_json(
        root / "registry/artifact_reachability.json", build_artifact_reachability(root)
    )
    _write_json(root / "registry/test_group_index.json", build_test_group_index(root))
    # This is last among source/registry projections. Installed-host evidence
    # must bind these exact engine bytes; later test receipts, evidence, and
    # completion publications are deliberately excluded to avoid a hash cycle.
    write_engine_identity(root)


def _run_candidate_command(root: Path, *arguments: str, timeout: int) -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "runtime.cli", "--root", str(root), *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode:
        detail = (completed.stdout + "\n" + completed.stderr).strip()[-4000:]
        raise ValueError(f"candidate command failed ({' '.join(arguments)}): {detail}")


def _certify_candidate_bytes(root: Path, artifacts: tuple[Path, ...]) -> None:
    """Own candidate-local receipts and one full certification before sealing."""
    from runtime.test_profiles import section_status

    # Projection rebuilding can stale only the sections whose exact input sets
    # changed. Refresh those chunks, preserving dependency order.
    for _ in range(2):
        status = section_status(root)
        stale = [row["section"] for row in status["sections"] if not row["current"]]
        if not stale:
            break
        progressed = False
        current = {row["section"]: row for row in status["sections"]}
        for name in stale:
            dependencies = current[name].get("dependencies", ())
            if all(current.get(item, {}).get("current") for item in dependencies):
                _run_candidate_command(root, "test-section", "run", name, timeout=360)
                progressed = True
        if not progressed:
            raise ValueError("candidate section dependencies cannot be made current")
    if not section_status(root)["valid"]:
        raise ValueError(
            "candidate section receipts remain stale after bounded refresh"
        )

    _run_candidate_command(
        root, "test-group", "run-stale", "--workers", "3", timeout=1800
    )
    # This is the sole owned whole-profile run for the final candidate.
    _run_candidate_command(root, "test-profile", "run", "full", timeout=1800)
    _run_candidate_command(root, "validate", timeout=120)

    # Evidence and completion are projections, never authority. Publish them
    # after the final receipts exist.  The static envelope inventory was sealed
    # before testing; rewriting it here would stale artifact reachability after
    # the candidate's final tests.
    from runtime.evidence_index import publish_index
    from scripts.build_completion_status import build as build_completion_status

    publish_index(root, artifacts=artifacts)
    _write_json(
        root / "registry/completion_status.json",
        build_completion_status(root),
        sort_keys=False,
    )


def _git_provenance(root: Path) -> dict[str, object]:
    """Return bounded source identity without making Git a hard dependency."""

    def query(*args: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        value = completed.stdout.strip()
        return value or None

    commit = query("rev-parse", "HEAD")
    commit_time = query("show", "-s", "--format=%cI", "HEAD")
    status = query("status", "--porcelain=v1", "--untracked-files=normal")
    return {
        "source_commit": commit,
        "source_commit_time": commit_time,
        "source_worktree_dirty": bool(status) if status is not None else None,
        "source_control_available": commit is not None,
    }


def _candidate_records(stage: Path) -> list[dict[str, object]]:
    records = []
    for path in sorted(
        stage.rglob("*"), key=lambda item: item.relative_to(stage).as_posix().casefold()
    ):
        if (
            not path.is_file()
            or path.is_symlink()
            or path.name == "AUDIT_EXPORT_MANIFEST.json"
        ):
            continue
        data = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(stage).as_posix(),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "mode": _mode(data),
            }
        )
    return records


def _assert_frozen_records(
    stage: Path, expected: list[dict[str, object]], *, phase: str
) -> None:
    current = _candidate_records(stage)
    if current != expected:
        raise ValueError(
            f"{phase} changed the sealed candidate tree; certification evidence is invalid"
        )


def _materialize_candidate(
    root: Path,
    stage: Path,
    output: Path,
    artifacts: tuple[Path, ...],
    *,
    rebuild_projections: bool = False,
) -> dict[str, object]:
    for source in included_files(root, output):
        relative = source.relative_to(root)
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    artifact_records = []
    seen: set[str] = set()
    for source in artifacts:
        name = source.name
        if name.casefold() in seen or source.suffix.casefold() != ".vsix":
            raise ValueError("audit artifacts must be unique existing VSIX files")
        seen.add(name.casefold())
        target = stage / "AUDIT_ARTIFACTS" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        artifact_records.append(
            {
                "path": target.relative_to(stage).as_posix(),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    if artifact_records:
        sums = "".join(
            f"{item['sha256']}  {Path(str(item['path'])).name}\n"
            for item in artifact_records
        )
        (stage / "AUDIT_ARTIFACTS/SHA256SUMS.txt").write_text(
            sums, encoding="ascii", newline="\n"
        )
        lines = [
            "# Pacify-X audit bundle\n\n",
            "Install/audit the exact VSIX under `AUDIT_ARTIFACTS/`; verify it against `AUDIT_ARTIFACTS/SHA256SUMS.txt`.\n\n",
            "The source projection is byte-preserved. `AUDIT_EXPORT_MANIFEST.json` contains the complete record list for every payload file except the manifest itself, whose self-exclusion is explicit.\n",
        ]
        (stage / "AUDIT_BUNDLE_README.md").write_text(
            "".join(lines), encoding="utf-8", newline="\n"
        )
    replay_contract = {
        "schema_version": "px.audit-replay-contract/1.0",
        "binding": "detached-exact-archive-receipt",
        "sidecar_name_rule": "<archive filename>.receipt.json",
        "payload_identity": "AUDIT_EXPORT_MANIFEST.json#/records_sha256",
        "reason": "An exact SHA-256 stored inside the archive it hashes would be self-referential. The adjacent receipt binds the final raw archive bytes; this in-archive contract binds that receipt to the payload identity.",
    }
    (stage / "AUDIT_REPLAY_CONTRACT.json").write_text(
        json.dumps(replay_contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if rebuild_projections:
        stage_artifacts = tuple(stage / str(item["path"]) for item in artifact_records)
        _rebuild_candidate_projections(stage)
        _certify_candidate_bytes(stage, stage_artifacts)
    records = _candidate_records(stage)
    records_sha = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    source_timestamp = (
        datetime.fromtimestamp(
            max(
                (path.stat().st_mtime for path in included_files(root, output)),
                default=0,
            ),
            tz=timezone.utc,
        )
        .isoformat()
        .replace("+00:00", "Z")
    )
    manifest = {
        "schema_version": "px.clean-source-audit-export/2.0",
        "bundle_mode": "full-audit-final-byte-candidate"
        if artifacts
        else "source-only-final-byte-candidate",
        "source_timestamp": source_timestamp,
        "build_time": source_timestamp,
        **_git_provenance(root),
        "archive_timestamp_policy": "fixed-1980-for-byte-determinism",
        "byte_policy": "source bytes copied unchanged; no export-time EOL, BOM, or encoding transformation",
        "certification_claim": False,
        "certification_note": "Candidate receipts and preflight are produced from the final payload bytes before manifest sealing; the unchanged archive extraction is then replay-validated against those bytes.",
        "record_scope": "Every bundle file except AUDIT_EXPORT_MANIFEST.json; the manifest is excluded to avoid a self-referential hash.",
        "record_count": len(records),
        "bundle_file_count": len(records) + 1,
        "records_sha256": records_sha,
        "records": records,
        "artifacts": artifact_records,
    }
    (stage / "AUDIT_EXPORT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def _write_archive(stage: Path, output: Path) -> None:
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(
            stage.rglob("*"),
            key=lambda item: item.relative_to(stage).as_posix().casefold(),
        ):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(stage).as_posix()
            data = path.read_bytes()
            info = zipfile.ZipInfo(relative, ARCHIVE_TIMESTAMP)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100000 | int(_mode(data), 8)) << 16
            archive.writestr(
                info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )


def create_clean_export(
    root: Path,
    output: Path,
    *,
    artifacts: tuple[Path, ...] = (),
    require_certification: bool | None = None,
) -> dict[str, object]:
    root = root.resolve(strict=True)
    output = output.resolve()
    artifacts = tuple(path.resolve(strict=True) for path in artifacts)
    if require_certification is None:
        require_certification = (root / "runtime/cli.py").is_file() and (
            root / "registry/test_profiles.json"
        ).is_file()
    if "certified" in output.stem.casefold():
        raise ValueError(
            "clean export produces an audit candidate and refuses a CERTIFIED filename; independent acceptance must confer that label"
        )
    if output.exists():
        raise FileExistsError("clean export refuses to overwrite an existing output")
    receipt_output = output.with_name(f"{output.name}.receipt.json")
    if receipt_output.exists():
        raise FileExistsError("clean export refuses to overwrite an existing receipt")
    output.parent.mkdir(parents=True, exist_ok=True)
    from runtime.resource_lifecycle import ResourceManager, RunState

    run_id = f"clean-export-{uuid4().hex}"
    manager = ResourceManager(root / ".engineering-bootstrap/export-resources.json")
    allowed_root = output.parent.resolve(strict=True)
    stage_record = manager.create_workspace(
        allowed_root,
        project_id=root.name,
        run_id=run_id,
        lane_id="final-candidate",
        creator="clean-source-export",
        prefix=".px-audit-candidate-",
    )
    stage = Path(str(stage_record.path))
    replay_record = None
    prepared = output.with_name(f".{output.name}.{uuid4().hex}.prepared")
    prepared_record = manager.register_path(
        prepared,
        allowed_cleanup_root=allowed_root,
        project_id=root.name,
        run_id=run_id,
        lane_id="archive",
        creator="clean-source-export",
    )
    receipt_prepared = output.with_name(
        f".{output.name}.{uuid4().hex}.receipt.prepared"
    )
    receipt_record = manager.register_path(
        receipt_prepared,
        allowed_cleanup_root=allowed_root,
        project_id=root.name,
        run_id=run_id,
        lane_id="archive-replay-receipt",
        creator="clean-source-export",
    )
    candidate_preflight: dict[str, object]
    replay_preflight: dict[str, object]
    try:
        manifest = _materialize_candidate(
            root,
            stage,
            output,
            artifacts,
            rebuild_projections=bool(require_certification),
        )
        stage_artifacts = tuple(
            stage / str(item["path"]) for item in manifest["artifacts"]
        )
        candidate_preflight = (
            _certification_preflight(stage, stage_artifacts)
            if require_certification
            else {
                "schema_version": "px.clean-export-preflight/1.0",
                "valid": True,
                "skipped": True,
                "reason": "certification deferred by caller",
            }
        )
        if not candidate_preflight["valid"]:
            raise ValueError(
                "final candidate certification failed: "
                + ", ".join(map(str, candidate_preflight.get("failed", ())))
            )
        _assert_frozen_records(
            stage, list(manifest["records"]), phase="candidate preflight"
        )
        _write_archive(stage, prepared)
        if require_certification:
            replay_record = manager.create_workspace(
                allowed_root,
                project_id=root.name,
                run_id=run_id,
                lane_id="extracted-replay",
                creator="clean-source-export",
                prefix=".px-audit-replay-",
            )
            replay = Path(str(replay_record.path))
            with zipfile.ZipFile(prepared) as archive:
                archive.extractall(replay)
            _assert_frozen_records(
                replay, list(manifest["records"]), phase="archive extraction"
            )
            replay_artifacts = tuple(
                replay / str(item["path"]) for item in manifest["artifacts"]
            )
            replay_preflight = _certification_preflight(replay, replay_artifacts)
            if not replay_preflight["valid"]:
                raise ValueError(
                    "extracted replay certification failed: "
                    + ", ".join(map(str, replay_preflight.get("failed", ())))
                )
            _assert_frozen_records(
                replay, list(manifest["records"]), phase="extracted replay"
            )
        else:
            replay_preflight = {
                "valid": True,
                "skipped": True,
                "reason": "certification deferred by caller",
            }
        os.replace(prepared, output)
        manager.promote_outputs(
            prepared_record.resource_id,
            [output],
            validated=bool(replay_preflight["valid"]),
        )
        archive_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
        receipt_body = {
            "schema_version": "px.clean-export-replay-receipt/1.0",
            "archive_name": output.name,
            "archive_sha256": archive_sha256,
            "records_sha256": manifest["records_sha256"],
            "candidate_preflight": candidate_preflight,
            "extracted_replay": replay_preflight,
            "valid": bool(candidate_preflight["valid"] and replay_preflight["valid"]),
        }
        receipt = {
            **receipt_body,
            "receipt_sha256": hashlib.sha256(
                json.dumps(receipt_body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
        receipt_prepared.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(receipt_prepared, receipt_output)
        manager.promote_outputs(
            receipt_record.resource_id,
            [receipt_output],
            validated=receipt["valid"],
        )
        manager.mark_run_ended(run_id, RunState.COMPLETED)
    except BaseException:
        manager.mark_run_ended(run_id, RunState.FAILED)
        raise
    finally:
        for record in (
            replay_record,
            stage_record,
            prepared_record,
            receipt_record,
        ):
            if record is None:
                continue
            try:
                manager.reclaim(
                    record.resource_id,
                    reason="clean export staging lifecycle closed",
                    apply=True,
                )
            except (OSError, ValueError, KeyError):
                pass
    records = list(manifest["records"])
    receipt_paths = [
        str(record["path"])
        for record in records
        if str(record["path"]).startswith(".engineering-bootstrap/test-evidence/")
    ]
    payload = {
        "schema_version": "px.clean-export-result/2.0",
        "file_count": manifest["bundle_file_count"],
        "record_count": manifest["record_count"],
        "records_sha256": manifest["records_sha256"],
        "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "replay_receipt": receipt_output.as_posix(),
        "hard_delete": False,
        "bundle_mode": manifest["bundle_mode"],
        "test_receipt_count": len(receipt_paths),
        "candidate_preflight": candidate_preflight,
        "extracted_replay": replay_preflight,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    parser.add_argument("--allow-uncertified", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            create_clean_export(
                args.root,
                args.output,
                artifacts=tuple(args.artifact),
                require_certification=not args.allow_uncertified,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
