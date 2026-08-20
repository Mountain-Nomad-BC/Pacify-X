"""Exact-version evidence namespace and semantic content-identity index."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Iterable
import zipfile


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version(root: Path) -> tuple[str, str]:
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    python = re.search(r'(?ms)^\[project\].*?^version\s*=\s*"([^"]+)"', pyproject)
    extension = json.loads(
        (root / "extension/package.json").read_text(encoding="utf-8")
    )["version"]
    if not python:
        raise ValueError("project version unavailable")
    return python.group(1), str(extension)


def _vsix_version(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            package = json.loads(archive.read("extension/package.json"))
        return str(package["version"])
    except (KeyError, OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError):
        return None


def _receipt_state(root: Path) -> tuple[dict[str, dict[str, object]], list[str]]:
    from .test_profiles import group_status, section_status

    limitations: list[str] = []
    states: dict[str, dict[str, object]] = {}
    try:
        sections = section_status(root)
        groups = group_status(root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return {}, [f"Certification receipt policy unavailable: {type(error).__name__}"]
    if not sections.get("required_sections"):
        limitations.append("No required test sections are declared.")
    if not groups.get("required_groups"):
        limitations.append("No required test groups are declared.")
    for row in sections.get("sections", ()):
        path = Path(str(row["receipt"])).resolve()
        states[path.as_posix().casefold()] = {
            "receipt_scope": "section",
            "receipt_id": row["section"],
            "passed": row["passed"],
            "fresh": row["fresh"],
            "dependencies_current": row["dependencies_current"],
            "current": row["current"],
            "expected_input_sha256": row["input_sha256"],
        }
    for row in groups.get("groups", ()):
        path = Path(str(row["receipt"])).resolve()
        states[path.as_posix().casefold()] = {
            "receipt_scope": "group",
            "receipt_id": row["group"],
            "passed": row["passed"],
            "fresh": row["fresh"],
            "current": row["current"],
            "expected_input_sha256": row["input_sha256"],
        }
    if not sections.get("valid"):
        stale = [
            row["section"] for row in sections.get("sections", ()) if not row["current"]
        ]
        limitations.append(
            "Required test sections are not current: " + ", ".join(stale)
        )
    if not groups.get("valid"):
        stale = [row["group"] for row in groups.get("groups", ()) if not row["current"]]
        limitations.append("Required test groups are not current: " + ", ".join(stale))
    return states, limitations


def build_index(root: Path, *, artifacts: Iterable[Path] = ()) -> dict[str, object]:
    root = root.resolve(strict=True)
    python_version, extension_version = _version(root)
    namespace = f"python-{python_version}__vscode-{extension_version}"
    receipt_states, receipt_issues = _receipt_state(root)
    blocking_reasons = list(receipt_issues)
    limitations: list[str] = []
    records: list[dict[str, object]] = []
    candidates = sorted(
        (root / ".engineering-bootstrap/test-evidence/sections").glob("*.json")
    )
    candidates += sorted(
        (root / ".engineering-bootstrap/test-evidence/groups").glob("*.json")
    )
    candidates += sorted(
        (root / ".engineering-bootstrap/test-evidence/profiles").glob("*.json")
    )
    for supplied in artifacts:
        path = supplied.resolve(strict=True)
        if not path.is_file():
            raise ValueError("evidence artifact must be a file")
        candidates.append(path)
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve(strict=True)
        if resolved in seen:
            continue
        seen.add(resolved)
        relative = (
            resolved.relative_to(root).as_posix()
            if resolved.is_relative_to(root)
            else resolved.name
        )
        is_vsix = resolved.suffix.casefold() == ".vsix"
        record: dict[str, object] = {
            "path": relative,
            "kind": "vsix" if is_vsix else "test-receipt",
            "bytes": resolved.stat().st_size,
            "sha256": _sha(resolved),
        }
        if is_vsix:
            version = _vsix_version(resolved)
            record.update(
                artifact_version=version,
                version_current=version == extension_version,
                locator_kind="repository-relative"
                if resolved.is_relative_to(root)
                else "caller-supplied-file",
            )
            if version != extension_version:
                blocking_reasons.append(
                    f"VSIX version mismatch: {relative} has {version!r}, expected {extension_version!r}."
                )
        else:
            state = receipt_states.get(resolved.as_posix().casefold())
            record["receipt_state"] = state or {
                "receipt_scope": "historical-or-optional",
                "current": False,
            }
        records.append(record)
    artifact_records = [row for row in records if row["kind"] == "vsix"]
    if not artifact_records:
        blocking_reasons.append(
            "No exact VSIX artifact is indexed; source/test evidence alone is not an installed-artifact certification."
        )
    elif not any(row.get("version_current") is True for row in artifact_records):
        blocking_reasons.append("No indexed VSIX matches the current extension version.")
    required_current = [
        state
        for state in receipt_states.values()
        if state["receipt_scope"] in {"section", "group"}
    ]
    if required_current and not all(
        state.get("current") is True for state in required_current
    ):
        blocking_reasons.append("At least one required receipt is stale or failed.")
    current_artifact_hashes = {
        str(row["sha256"])
        for row in artifact_records
        if row.get("version_current") is True
    }
    from .engine_identity import validate_engine_identity

    engine_identity = validate_engine_identity(root)
    if not engine_identity["valid"]:
        blocking_reasons.append("The exact engine identity manifest is missing or stale.")
    platform_semantics: dict[str, dict[str, object]] = {}
    for platform, relative in (
        ("win32", "extension/evidence/installed-vsix-smoke.json"),
        ("linux", "extension/evidence/installed-vsix-smoke-linux.json"),
    ):
        path = root / relative
        if not path.is_file():
            blocking_reasons.append(f"Required {platform} installed-VSIX smoke evidence is missing.")
            continue
        try:
            smoke = json.loads(path.read_text(encoding="utf-8"))
            artifact = smoke["artifact"]
            host = smoke["host"]
            listener = host["listener_health"]
            artifact_sha = str(artifact["sha256_after"])
            smoke_limitations = [
                str(item) for item in host.get("limitations", [])
            ] + [str(item) for item in listener.get("limitations", [])]
            bound = (
                smoke.get("platform") == platform
                and smoke.get("schema_version") == "px.installed-vsix-certification/1.1"
                and artifact.get("unchanged") is True
                and artifact.get("sha256_before") == artifact_sha
                and artifact_sha in current_artifact_hashes
                and smoke.get("engine_connected") is True
                and smoke.get("engine_identity", {}).get("manifest_sha256")
                == engine_identity.get("manifest_sha256")
                and smoke.get("engine_identity", {}).get("tree_sha256")
                == engine_identity.get("tree_sha256")
                and smoke.get("engine_identity", {}).get("file_total")
                == engine_identity.get("file_total")
                and smoke.get("process_lifecycle", {}).get("process_tree_closed_verified") is True
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            blocking_reasons.append(f"Required {platform} installed-VSIX smoke evidence is invalid: {type(error).__name__}.")
            continue
        records.append(
            {
                "path": relative,
                "kind": "installed-vsix-smoke",
                "platform": platform,
                "bytes": path.stat().st_size,
                "sha256": _sha(path),
                "artifact_sha256": artifact_sha,
                "artifact_bound": bound,
                "engine_identity": smoke.get("engine_identity"),
                "coverage_tier": listener.get("coverage_tier"),
                "coverage_complete": listener.get("coverage_complete") is True,
                "limitations": sorted(set(smoke_limitations)),
            }
        )
        if not bound:
            blocking_reasons.append(f"Required {platform} installed-VSIX smoke does not bind the current exact artifact and engine manifest.")
        live = host.get("live_dashboard", {})
        platform_semantics[platform] = {
            "source_version": live.get("source", {}).get("version"),
            "source_mode": live.get("source", {}).get("mode"),
            "canonical_counts_match": live.get("canonical_counts_match"),
            "counts": live.get("counts"),
        }
        for item in smoke_limitations:
            limitations.append(f"{platform} installed smoke: {item}")
        if listener.get("coverage_complete") is not True:
            limitations.append(
                f"{platform} installed smoke is coverage tier {listener.get('coverage_tier', 'unknown')} and partial."
            )
    if set(platform_semantics) == {"win32", "linux"} and (
        platform_semantics["win32"] != platform_semantics["linux"]
    ):
        blocking_reasons.append(
            "Windows and Linux installed-host platform-independent dashboard semantics differ."
        )
    blocking_reasons = sorted(set(blocking_reasons))
    limitations = sorted(set(limitations))
    return {
        "schema_version": "px.current-evidence-index/1.3",
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "namespace": namespace,
        "identity": {
            "python_version": python_version,
            "extension_version": extension_version,
        },
        "engine_identity": engine_identity,
        "authority": "Exact byte identities plus live semantic receipt currentness; historical evidence is never current by presence alone.",
        "valid": not blocking_reasons,
        "artifact_count": len(artifact_records),
        "required_receipt_count": len(required_current),
        "current_required_receipt_count": sum(
            state.get("current") is True for state in required_current
        ),
        "record_count": len(records),
        "records": records,
        "blocking_reasons": blocking_reasons,
        "limitations": limitations,
    }


def publish_index(
    root: Path, *, artifacts: Iterable[Path] = ()
) -> tuple[Path, Path, dict[str, object]]:
    root = root.resolve(strict=True)
    value = build_index(root, artifacts=artifacts)
    targets = [
        root / "registry/current_evidence_index.json",
        root / "evidence/releases" / str(value["namespace"]) / "EVIDENCE_INDEX.json",
    ]
    serialized = json.dumps(value, indent=2, sort_keys=True) + "\n"
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        prepared = target.with_name(f".{target.name}.prepared")
        prepared.write_text(serialized, encoding="utf-8", newline="\n")
        os.replace(prepared, target)
    return targets[0], targets[1], value
