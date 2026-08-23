"""Atomic, clean-workspace, digest-bound release certification."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable
import uuid
import xml.etree.ElementTree as ET
import venv

from .corrective_release import validate_corrective_ledger
from .coverage_assurance import validate_coverage_evidence
from .exact_tool_certification import certify_exact_tools
from .file_lock import FileLock
from .generated_artifacts import validate_generated_artifacts
from .full_repair import validate_full_repair_ledger
from .release_artifacts import classify_tree, verify_frozen_product
from .release_distribution import (
    bind_artifact_set,
    build_release_artifacts_once,
    install_exact_wheel,
    verify_artifact_records,
)
from .release_environment import (
    build_wheelhouse_manifest,
    certification_platform_binding,
    offline_install_command,
    scrub_release_environment,
    toolchain_identity,
    validate_certification_platform,
)
from .release_evidence import build_evidence_manifest, verify_evidence_manifest
from .release_identity import (
    authoritative_version,
    capture_git_identity,
    validate_version_surfaces,
    verify_recorded_git_identity,
)
from .release_signing import sign_certificate, verify_certificate_signature
from .repository_scope import is_external_environment_relative
from .test_runner import run_test_command


FINALIZER_CARDS = {"REL-010-C", "REL-010-E", "REL-011-FULL-REPAIR"}
FINALIZER_FULL_REPAIR_PENDING = frozenset(
    {"PC-001", "PC-002", "PC-003", "PC-004", "PC-005", "PC-006", "PC-037"}
)
MACHINE_LOCAL_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]|/(?:users|home|tmp|var/tmp)/)")
PROJECT_ESCAPE_PATH = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")
WINDOWS_LOCAL_FRAGMENT = re.compile(r"(?i)[a-z]:[\\/][^\s\"'<>]*")
POSIX_LOCAL_FRAGMENT = re.compile(r"(?i)/(?:users|home|var/tmp|tmp)/[^\s\"'<>]*")
RELATIVE_PARENT_FRAGMENT = re.compile(r"(?:(?:\.\.[\\/])+)[^\s\"'<>]*")
ALLOWED_RELEASE_TEST_SKIPS = {
    (
        "tests.test_build_installed_host_control_evidence",
        "test_current_host_receipt_remains_bound_when_retained_vsix_is_available",
    ): "retained installed VSIX is external host custody",
    (
        "tests.test_clean_source_export",
        "test_posix_unzip_restores_and_directly_executes_script",
    ): "ordinary POSIX unzip execution is verified on a host with unzip",
    (
        "tests.test_native_skills.NativeSkillTests",
        "test_live_workspace_original_backup_restores_exactly",
    ): "native migration has not run",
    (
        "tests.test_skill_studio",
        "test_skill_source_rejects_duplicate_canonical_directory_aliases",
    ): "host filesystem does not permit distinct case aliases",
}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_coverage_binding(
    root: Path, release: str, certificate: dict[str, Any]
) -> dict[str, Any]:
    """Verify that a certificate names and hashes valid executed coverage evidence."""
    errors: list[str] = []
    relative = str(certificate.get("coverage_evidence", ""))
    expected_prefix = f"evidence/releases/{release}/"
    path = (root / relative).resolve(strict=False)
    release_root = (root / "evidence" / "releases" / release).resolve()
    try:
        path.relative_to(release_root)
    except ValueError:
        errors.append("certificate coverage evidence is outside its release root")
    if not relative.startswith(expected_prefix) or not path.is_file():
        errors.append(
            "certificate coverage evidence is missing or outside its release root"
        )
    elif _sha(path) != certificate.get("coverage_evidence_sha256"):
        errors.append("certificate coverage-evidence file hash mismatch")
    else:
        coverage = validate_coverage_evidence(root, path)
        errors.extend(coverage["errors"])
    return {"valid": not errors, "path": relative, "errors": errors}


def _write_supply_chain_evidence(
    evidence_dir: Path,
    *,
    release: str,
    source_control: dict[str, Any],
    product_digest: str,
    artifacts: list[dict[str, Any]],
    toolchain: dict[str, Any],
) -> dict[str, str]:
    """Write deterministic checksums, an SBOM, and provenance for exact built bytes."""
    subjects = [
        {
            "name": str(item["filename"]),
            "digest": {"sha256": str(item["sha256"])},
            "size_bytes": int(item["size_bytes"]),
        }
        for item in sorted(artifacts, key=lambda value: str(value["filename"]))
    ]
    checksums = evidence_dir / "SHA256SUMS.txt"
    checksums.write_text(
        "".join(f"{item['digest']['sha256']}  {item['name']}\n" for item in subjects),
        encoding="utf-8",
        newline="\n",
    )
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "PACIFY-X", "version": release}
        },
        "components": [
            {
                "type": "file",
                "name": item["name"],
                "hashes": [{"alg": "SHA-256", "content": item["digest"]["sha256"]}],
                "properties": [
                    {"name": "pacify-x:size-bytes", "value": str(item["size_bytes"])}
                ],
            }
            for item in subjects
        ],
    }
    _dump(evidence_dir / "sbom.cdx.json", sbom)
    provenance = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {"name": item["name"], "digest": item["digest"]} for item in subjects
        ],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://github.com/Mountain-Nomad-BC/Pacify-X/release/v1",
                "externalParameters": {"release": release},
                "resolvedDependencies": [
                    {
                        "uri": str(source_control.get("repository", "")),
                        "digest": {
                            "gitCommit": str(source_control.get("commit", "")),
                            "gitTree": str(source_control.get("tree", "")),
                            "productSha256": product_digest,
                        },
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": "engineering-bootstrap atomic release finalizer"},
                "metadata": {"invocationId": str(source_control.get("tag", ""))},
                "byproducts": [{"name": "release-toolchain", "content": toolchain}],
            },
        },
    }
    _dump(evidence_dir / "provenance.intoto.json", provenance)
    return {
        "checksums": "SHA256SUMS.txt",
        "sbom": "sbom.cdx.json",
        "provenance": "provenance.intoto.json",
    }


def _junit_totals(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    tag = root.tag.rsplit("}", 1)[-1]
    if tag == "testsuite":
        suites = [root]
    else:
        suites = [
            item for item in list(root) if item.tag.rsplit("}", 1)[-1] == "testsuite"
        ]
    return {
        name: sum(int(suite.attrib.get(name, 0)) for suite in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }


def _junit_case_gate(path: Path, marker: str) -> dict[str, Any]:
    """Require a named test surface to be present and entirely green."""
    root = ET.parse(path).getroot()
    cases = [
        case
        for case in root.iter("testcase")
        if marker in str(case.attrib.get("classname", ""))
        or marker in str(case.attrib.get("name", ""))
    ]
    failures = sum(1 for case in cases if case.find("failure") is not None)
    errors = sum(1 for case in cases if case.find("error") is not None)
    skipped = sum(1 for case in cases if case.find("skipped") is not None)
    return {
        "valid": bool(cases) and failures == errors == skipped == 0,
        "tests": len(cases),
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "marker": marker,
    }


def _junit_skip_policy_gate(path: Path) -> dict[str, Any]:
    """Allow only reviewed host-conditional skips; reject every unknown skip."""

    root = ET.parse(path).getroot()
    allowed: list[str] = []
    unexpected: list[str] = []
    for case in root.iter("testcase"):
        skipped = case.find("skipped")
        if skipped is None:
            continue
        identity = (
            str(case.attrib.get("classname", "")),
            str(case.attrib.get("name", "")),
        )
        expected_reason = ALLOWED_RELEASE_TEST_SKIPS.get(identity)
        observed_reason = " ".join(
            filter(None, (str(skipped.attrib.get("message", "")), skipped.text or ""))
        )
        label = f"{identity[0]}::{identity[1]}"
        if expected_reason and expected_reason in observed_reason:
            allowed.append(label)
        else:
            unexpected.append(label)
    return {
        "valid": not unexpected,
        "allowed_count": len(allowed),
        "allowed": sorted(allowed),
        "unexpected_count": len(unexpected),
        "unexpected": sorted(unexpected),
    }


def _sanitize_junit_metadata(path: Path) -> None:
    """Remove host identity and machine-local paths from public test evidence."""
    tree = ET.parse(path)
    root = tree.getroot()
    for suite in root.iter("testsuite"):
        suite.attrib.pop("hostname", None)
    for element in root.iter():
        for key, value in tuple(element.attrib.items()):
            element.set(key, _redact_junit_text(value))
        if element.text:
            element.text = _redact_junit_text(element.text)
        if element.tail:
            element.tail = _redact_junit_text(element.tail)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _redact_junit_text(value: str) -> str:
    redacted = WINDOWS_LOCAL_FRAGMENT.sub("[machine-local-path]", value)
    redacted = POSIX_LOCAL_FRAGMENT.sub("[machine-local-path]", redacted)
    return RELATIVE_PARENT_FRAGMENT.sub("[machine-local-path]", redacted)


def _junit_metadata_gate(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    hostnames = [
        suite.attrib["hostname"]
        for suite in root.iter("testsuite")
        if "hostname" in suite.attrib
    ]
    paths = _portable_payload_gate(ET.tostring(root, encoding="unicode"))
    errors = [
        *("JUnit evidence contains host identity" for _ in hostnames),
        *paths["errors"],
    ]
    return {
        "valid": not errors,
        "hostname_count": len(hostnames),
        "nonportable_path_count": paths["nonportable_path_count"],
        "errors": errors,
    }


def _compact_coverage_contexts(root: Path, coverage_path: Path) -> dict[str, Any]:
    """Retain dynamic contexts only for modules governed by coverage policy."""

    policy = _json(root / "policies/coverage-assurance.json")
    governed_modules = sorted(
        {
            str(module).replace("\\", "/")
            for rule in policy.get("classes", {}).values()
            for module in rule.get("modules", ())
        }
    )
    coverage = _json(coverage_path)
    files = coverage.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("coverage evidence files must be an object")
    retained = 0
    removed = 0
    nested_removed = 0

    def strip_nested_contexts(value: object) -> None:
        nonlocal nested_removed
        if isinstance(value, dict):
            for key in list(value):
                if key == "contexts":
                    value.pop(key, None)
                    nested_removed += 1
                else:
                    strip_nested_contexts(value[key])
        elif isinstance(value, list):
            for item in value:
                strip_nested_contexts(item)

    for name, record in files.items():
        if not isinstance(record, dict):
            continue
        normalized = str(name).replace("\\", "/")
        governed = any(
            normalized == module or normalized.endswith("/" + module)
            for module in governed_modules
        )
        if "contexts" in record:
            if governed:
                retained += 1
            else:
                record.pop("contexts", None)
                removed += 1
        # Coverage.py repeats line contexts in function and class projections.
        # File-level contexts are the canonical policy input, so remove only
        # those redundant nested copies while keeping all summaries/branches.
        strip_nested_contexts(record.get("functions"))
        strip_nested_contexts(record.get("classes"))
    meta = coverage.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["pacify_x_context_scope"] = "policy-governed-modules"
        meta["pacify_x_context_modules"] = governed_modules
    prepared = coverage_path.with_name(f".{coverage_path.name}.compacted")
    prepared.write_text(
        json.dumps(coverage, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    os.replace(prepared, coverage_path)
    return {
        "governed_module_count": len(governed_modules),
        "files_with_contexts_retained": retained,
        "files_with_contexts_removed": removed,
        "nested_context_fields_removed": nested_removed,
        "bytes": coverage_path.stat().st_size,
    }


def _release_environment_gate(
    root: Path, python_executable: str, environment: dict[str, str]
) -> dict[str, Any]:
    process = subprocess.run(
        [
            python_executable,
            "-m",
            "runtime.cli",
            "--root",
            str(root),
            "release",
            "environment",
        ],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
    )
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError:
        return {
            "schema_version": "1.0",
            "valid": False,
            "errors": [
                f"isolated release environment produced invalid output: {process.stderr[-1000:]}"
            ],
        }
    if process.returncode != 0 and result.get("valid") is True:
        result = {
            **result,
            "valid": False,
            "errors": [
                *result.get("errors", []),
                f"environment command exited {process.returncode}",
            ],
        }
    return result


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(value)
    unsigned.pop("certificate_sha256", None)
    digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**unsigned, "certificate_sha256": digest}


def _commit_release_evidence(release_root: Path, destination: Path) -> dict[str, Any]:
    """Add signed evidence without overwriting existing pre-release records."""
    source_files: list[tuple[Path, Path]] = []
    errors: list[str] = []
    for source in sorted(
        release_root.rglob("*"), key=lambda item: item.as_posix().casefold()
    ):
        relative = source.relative_to(release_root)
        if source.is_symlink() or (
            hasattr(source, "is_junction") and source.is_junction()
        ):
            errors.append(f"release evidence contains a link: {relative.as_posix()}")
        elif source.is_file():
            source_files.append((source, relative))
    collisions = [
        relative.as_posix()
        for _, relative in source_files
        if (destination / relative).exists()
    ]
    if collisions:
        errors.extend(
            f"release evidence collision: {relative}" for relative in collisions
        )
    if errors:
        return {"valid": False, "copied_file_count": 0, "errors": errors}
    try:
        destination.mkdir(parents=True, exist_ok=True)
        for source, relative in source_files:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
    except OSError as error:
        return {
            "valid": False,
            "copied_file_count": 0,
            "errors": [
                f"release evidence commit failed: {type(error).__name__}: {error}"
            ],
        }
    return {"valid": True, "copied_file_count": len(source_files), "errors": []}


def _portable_payload_gate(value: object) -> dict[str, Any]:
    """Reject absolute or parent-traversing paths from release metadata."""
    hits: list[str] = []

    def visit(item: object, pointer: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                visit(child, f"{pointer}/{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{pointer}/{index}")
        elif isinstance(item, str):
            if MACHINE_LOCAL_PATH.search(item) or PROJECT_ESCAPE_PATH.search(item):
                hits.append(pointer or "/")

    visit(value, "")
    return {
        "valid": not hits,
        "nonportable_path_count": len(hits),
        "errors": [f"nonportable path at {pointer}" for pointer in hits],
    }


def _eligible_ledger(root: Path) -> list[str]:
    ledger = _json(root / "registry/corrective_release_ledger.json")
    errors = []
    for card in ledger["cards"]:
        if card["id"] in FINALIZER_CARDS:
            if card["status"] not in {"open", "in_progress", "passed"}:
                errors.append(f"{card['id']}: finalizer card has invalid entry state")
            continue
        if card["priority"] in {"P0", "P1"} and card["status"] != "passed":
            errors.append(f"{card['id']}: blocking card is not passed")
        if card["priority"] not in {"P0", "P1"} and card["status"] not in {
            "passed",
            "rejected_with_evidence",
            "deferred_with_owner",
        }:
            errors.append(f"{card['id']}: nonblocking card lacks final disposition")
    # The finalizer itself supplies the executed proof for PC-001 through
    # PC-006. PC-037 can close only after those exact bytes are published and
    # independently downloaded, so neither group may be falsely pre-passed.
    full_repair = validate_full_repair_ledger(
        root,
        require_all_passed=True,
        allowed_pending=FINALIZER_FULL_REPAIR_PENDING,
    )
    errors.extend(full_repair["errors"])
    return errors


def _certificate_ledger_errors(root: Path) -> list[str]:
    """Admit only the circular cards that certification/publication can close."""
    corrective = validate_corrective_ledger(
        root,
        require_blocking_passed=True,
        allow_finalizer_in_progress=True,
    )
    full_repair = validate_full_repair_ledger(
        root,
        require_all_passed=True,
        allowed_pending=FINALIZER_FULL_REPAIR_PENDING,
    )
    return [*corrective["errors"], *full_repair["errors"]]


def run_release_gates(
    root: Path,
    evidence_dir: Path,
    *,
    release_python: str,
    artifact_dir: Path,
    artifact_records: list[dict[str, Any]],
    toolchain: dict[str, Any],
    wheelhouse_manifest: dict[str, Any],
    evidence_locator_prefix: str,
) -> dict[str, Any]:
    """Run every release gate against the isolated staged product tree."""
    started = time.monotonic()
    environment = scrub_release_environment()
    wheel_record = next(
        (item for item in artifact_records if item.get("type") == "wheel"), None
    )
    if wheel_record is None:
        return {
            "schema_version": "2.0",
            "valid": False,
            "errors": ["exact release wheel is missing"],
            "gates": {},
        }
    wheel_path = artifact_dir / str(wheel_record["filename"])
    environment_quarantine = Path(tempfile.gettempdir()) / "pacify-x-release-quarantine"
    environment_quarantine.mkdir(parents=True, exist_ok=True)
    installed_root = Path(
        tempfile.mkdtemp(prefix="installed-wheel-", dir=environment_quarantine)
    )
    release_home = installed_root / "home"
    release_state = release_home / ".local" / "state"
    release_state.mkdir(parents=True)
    environment.update(
        {
            "HOME": str(release_home),
            "USERPROFILE": str(release_home),
            "XDG_STATE_HOME": str(release_state),
        }
    )
    install_started = time.monotonic()
    installed = install_exact_wheel(
        wheel_path, str(wheel_record["sha256"]), installed_root
    )
    toolchain_gate = {
        "valid": wheelhouse_manifest.get("valid") is True,
        "duration_seconds": round(time.monotonic() - install_started, 6),
        "identity": toolchain,
        "wheelhouse_manifest_sha256": wheelhouse_manifest.get("manifest_sha256"),
        "custody_class": "external_temporary_quarantine",
        "custody_id": Path(release_python).resolve().parent.parent.name,
        "hard_delete": False,
    }
    installed_receipt = {
        "schema_version": "1.0",
        **installed,
        "expected_wheel_sha256": wheel_record["sha256"],
        "artifact_filename": wheel_record["filename"],
    }
    _dump(evidence_dir / "installed-wheel.json", installed_receipt)
    from .test_profiles import resolve_test_profile

    profile = resolve_test_profile(root, "release")
    tests_started = time.monotonic()
    junit_path = evidence_dir / "full-tests.junit.xml"
    coverage_path = evidence_dir / "coverage.json"
    test_command = [
        str(release_python),
        "-m",
        "coverage",
        "run",
        "--rcfile=.coveragerc",
        "-m",
        "pytest",
        *profile["command"][3:],
        f"--junitxml={junit_path}",
    ]
    environment.update(
        {
            "PACIFY_X_CERTIFIED_WHEEL": str(wheel_path),
            "PACIFY_X_CERTIFIED_WHEEL_SHA256": str(wheel_record["sha256"]),
            "PACIFY_X_RELEASE_BUILD_PROHIBITED": "1",
            "COVERAGE_FILE": str(
                environment_quarantine / f"coverage-{wheel_record['sha256']}.data"
            ),
        }
    )
    test_process = run_test_command(
        test_command,
        cwd=root,
        environment=environment,
        timeout_seconds=profile["timeout_seconds"],
    )
    test_stdout = str(test_process.get("stdout", ""))
    test_stderr = str(test_process.get("stderr", ""))
    test_exit = test_process.get("exit_code")
    test_timed_out = bool(test_process.get("timed_out"))
    test_log = evidence_dir / "full-tests.log"
    test_log.parent.mkdir(parents=True, exist_ok=True)
    test_log.write_text(test_stdout + test_stderr, encoding="utf-8")
    if junit_path.is_file():
        _sanitize_junit_metadata(junit_path)
        totals = _junit_totals(junit_path)
        skip_policy_gate = _junit_skip_policy_gate(junit_path)
    else:
        totals = {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}
        skip_policy_gate = {
            "valid": False,
            "allowed_count": 0,
            "allowed": [],
            "unexpected_count": 0,
            "unexpected": [],
        }
    coverage_command = [
        str(release_python),
        "-m",
        "coverage",
        "json",
        "--rcfile=.coveragerc",
        "--show-contexts",
        "-o",
        str(coverage_path),
    ]
    coverage_process = run_test_command(
        coverage_command,
        cwd=root,
        environment=environment,
        timeout_seconds=min(float(profile["timeout_seconds"]), 300.0),
    )
    if coverage_path.is_file() and coverage_process["valid"]:
        coverage_compaction = _compact_coverage_contexts(root, coverage_path)
        coverage_gate = validate_coverage_evidence(root, coverage_path)
    else:
        coverage_compaction = {
            "governed_module_count": 0,
            "files_with_contexts_retained": 0,
            "files_with_contexts_removed": 0,
            "nested_context_fields_removed": 0,
            "bytes": 0,
        }
        coverage_gate = {
            "schema_version": "1.0",
            "valid": False,
            "coverage_sha256": None,
            "errors": [
                "executed coverage evidence was not generated",
                str(coverage_process.get("stderr", ""))[-2000:],
            ],
        }
    artifact_binding = bind_artifact_set(
        artifact_dir,
        artifact_records,
        source_product_digest=classify_tree(root)["product_digest"],
        version=authoritative_version(root),
        source_root=root,
    )
    _dump(evidence_dir / "artifact-inspection.json", artifact_binding)
    gates: dict[str, Any] = {
        "release_toolchain": toolchain_gate,
        "full_tests": {
            "valid": test_exit == 0
            and not test_timed_out
            and totals["tests"] > 0
            and totals["failures"] == totals["errors"] == 0
            and skip_policy_gate["valid"],
            "exit_code": test_exit,
            "timed_out": test_timed_out,
            "duration_seconds": round(time.monotonic() - tests_started, 6),
            "log": f"{evidence_locator_prefix}/full-tests.log",
            **totals,
        },
        "full_test_skip_policy": skip_policy_gate,
        "exact_artifact_install": {
            "valid": installed["valid"]
            and installed.get("installed_wheel_sha256") == wheel_record["sha256"],
            "errors": installed["errors"],
        },
        "artifact_binding": {
            "valid": artifact_binding["valid"],
            "errors": artifact_binding["errors"],
        },
        "executed_branch_coverage": {
            **coverage_gate,
            "context_compaction": coverage_compaction,
        },
    }
    gates["installed_wheel"] = (
        _junit_case_gate(junit_path, "test_installed_wheel_e2e")
        if junit_path.is_file()
        else {
            "valid": False,
            "tests": 0,
            "errors": 1,
            "marker": "test_installed_wheel_e2e",
        }
    )
    gates["junit_metadata_portability"] = (
        _junit_metadata_gate(junit_path)
        if junit_path.is_file()
        else {
            "valid": False,
            "hostname_count": 0,
            "nonportable_path_count": 0,
            "errors": ["JUnit evidence is missing"],
        }
    )
    exact = certify_exact_tools(
        root,
        aggregate_timeout_seconds=1_200,
        receipt_path=evidence_dir / "exact-tools.json",
        allow_cache=False,
        python_executable=str(release_python),
    )
    gates["exact_tools"] = {
        "valid": exact["valid"],
        "denominator": exact["admitted_tools"] + exact["domain_wrappers"],
        "passed": exact["passed_tools"] + exact["passed_domain_wrappers"],
        "duration_seconds": exact["duration_seconds"],
        "errors": exact["errors"],
    }
    from .release_audit import audit_framework
    from .structural_integrity import audit_structural_integrity
    from .dependency_audit import validate_dependency_closure
    from .registry_envelope import validate_registry_envelopes
    from .external_evidence import validate_external_evidence
    from .contracts import validate_contract_corpus
    from .effect_surface import validate_effect_surfaces
    from .evidence_portability import validate_evidence_portability
    from .graph_registry import validate_graph_artifacts
    from .integration_registry import validate_integrations
    from .registry import validate_registry
    from .licensing import validate_licensing
    from .sanitation_assurance import build_sanitation_summary
    from scripts.audit_sanitization import audit as audit_sanitization

    licensing_result = validate_licensing(root)
    checks = {
        "release_audit": audit_framework(root, require_external_manifests=True),
        "structural_integrity": audit_structural_integrity(root),
        "generated_artifacts": validate_generated_artifacts(root),
        "dependency_ownership": validate_dependency_closure(root),
        "registry_envelopes": validate_registry_envelopes(root),
        "external_evidence": validate_external_evidence(root, strict=True),
        "contracts": validate_contract_corpus(root),
        "graphs": validate_graph_artifacts(root),
        "integrations": validate_integrations(root, smoke=True),
        "registry": validate_registry(root),
        "corrective_release": validate_corrective_ledger(
            root,
            require_blocking_passed=True,
            allow_finalizer_in_progress=True,
        ),
        "effect_surfaces": validate_effect_surfaces(root),
        "evidence_portability": validate_evidence_portability(root),
        "release_environment": _release_environment_gate(
            root, str(release_python), environment
        ),
        "licensing": licensing_result,
    }
    for name, result in checks.items():
        errors = list(result.get("errors", []))
        if not errors and isinstance(result.get("checks"), list):
            errors = [
                f"{item.get('id', 'unknown')}: {item.get('detail', 'failed')}"
                for item in result["checks"]
                if not item.get("passed", False)
            ]
        gates[name] = {
            "valid": bool(result.get("valid", result.get("complete", False))),
            "errors": errors,
        }
    sanitation = audit_sanitization(root)
    sanitation_controls = build_sanitation_summary(root, sanitation, licensing_result)
    _dump(evidence_dir / "sanitation-controls.json", sanitation_controls)
    gates["sanitation_summary"] = {
        "valid": bool(sanitation_controls["valid"]),
        "corpus_sha256": sanitation_controls["corpus_sha256"],
        "file_count": sanitation_controls["file_count"],
        "errors": sanitation_controls["errors"],
    }
    for control_name, control in sanitation_controls["gates"].items():
        gates[f"sanitation_{control_name}"] = {
            "valid": control.get("status") == "passed",
            "status": control.get("status"),
            "tool": control.get("tool"),
            "corpus": control.get("corpus"),
            "corpus_sha256": control.get("corpus_sha256"),
            "exclusions": control.get("exclusions", []),
            "limitations": control.get("limitations"),
            "finding_count": len(control.get("findings", [])),
            "disposition": control.get("disposition"),
            "errors": []
            if control.get("status") == "passed"
            else [f"{control_name} did not pass"],
        }
    gates["publishable_evidence_portability"] = _portable_payload_gate(gates)
    valid = all(item["valid"] for item in gates.values())
    result = {
        "schema_version": "1.0",
        "valid": valid,
        "gate_count": len(gates),
        "gates": gates,
        "duration_seconds": round(time.monotonic() - started, 6),
    }
    _dump(evidence_dir / "gate-summary.json", result)
    return result


def _copy_clean(source: Path, destination: Path) -> None:
    source = source.resolve()
    generated = shutil.ignore_patterns(
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "*.pyc",
        "*.pyo",
        "*.egg-info",
        "build",
        "dist",
        "release.lock",
        "release-transaction.json",
    )

    def ignore(directory: str, names: list[str]) -> set[str]:
        relative_directory = Path(directory).resolve().relative_to(source)
        ignored = set(generated(directory, names))
        for name in names:
            if is_external_environment_relative(relative_directory / name):
                ignored.add(name)
        return ignored

    shutil.copytree(
        source,
        destination,
        ignore=ignore,
    )


def finalize_release(
    root: Path,
    release: str | None = None,
    *,
    signing_key: Path | None = None,
    wheelhouse: Path | None = None,
    artifact_dir: Path | None = None,
    gate_runner: Callable[..., dict[str, Any]] = run_release_gates,
    mutation_hook: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Certify one tagged source snapshot and one immutable artifact build."""
    root = root.resolve()
    asserted = release
    versions = validate_version_surfaces(root, asserted=asserted)
    release = versions["authoritative_version"]
    errors = list(versions["errors"])
    errors.extend(_eligible_ledger(root))
    if signing_key is None:
        configured = os.environ.get("PACIFY_X_RELEASE_SIGNING_KEY")
        signing_key = Path(configured) if configured else None
    if wheelhouse is None:
        configured = os.environ.get("PACIFY_X_RELEASE_WHEELHOUSE")
        wheelhouse = Path(configured) if configured else None
    if signing_key is None:
        errors.append("release signing key is required")
    if wheelhouse is None:
        errors.append("hash-locked release wheelhouse is required")
    if errors:
        return {
            "valid": False,
            "certified": False,
            "published": False,
            "errors": errors,
        }
    assert signing_key is not None and wheelhouse is not None
    try:
        signing_key = signing_key.resolve(strict=True)
        wheelhouse = wheelhouse.resolve(strict=True)
    except OSError as error:
        return {
            "valid": False,
            "certified": False,
            "published": False,
            "errors": [str(error)],
        }
    try:
        relative_key = signing_key.relative_to(root)
        if not relative_key.parts or relative_key.parts[0] != ".git":
            return {
                "valid": False,
                "certified": False,
                "published": False,
                "errors": [
                    "release private key must be outside the tracked repository"
                ],
            }
    except ValueError:
        pass
    source_control = capture_git_identity(root, version=release)
    if not source_control["valid"]:
        return {
            "valid": False,
            "certified": False,
            "published": False,
            "errors": source_control["errors"],
        }
    initial = classify_tree(root)
    if not initial["valid"]:
        return {
            "valid": False,
            "certified": False,
            "published": False,
            "errors": initial["errors"],
        }
    wheelhouse_manifest = build_wheelhouse_manifest(
        wheelhouse, root / "requirements-release.lock"
    )
    if not wheelhouse_manifest["valid"]:
        return {
            "valid": False,
            "certified": False,
            "published": False,
            "errors": wheelhouse_manifest["errors"],
        }
    run_id = f"rel-{release}-{uuid.uuid4().hex[:12]}"
    staging_base = Path(tempfile.gettempdir()) / "pacify-x-release-staging" / run_id
    selected_artifact_dir = (artifact_dir or (staging_base / "artifacts")).resolve()
    lock_path = root / ".engineering-bootstrap/release.lock"
    with FileLock(lock_path, timeout_seconds=5.0):
        release_quarantine = Path(tempfile.gettempdir()) / "pacify-x-release-quarantine"
        release_quarantine.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=release_quarantine))
        staged = directory / "product"
        _copy_clean(root, staged)
        frozen = classify_tree(staged)
        if not frozen["valid"] or frozen["product_digest"] != initial["product_digest"]:
            return {
                "valid": False,
                "certified": False,
                "published": False,
                "errors": [
                    *frozen["errors"],
                    "staged source does not match captured product",
                ],
            }
        toolchain_root = directory / "release-toolchain"
        venv.EnvBuilder(with_pip=True).create(toolchain_root)
        release_python = toolchain_root / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        environment = scrub_release_environment()
        install = subprocess.run(
            offline_install_command(
                str(release_python), staged / "requirements-release.lock", wheelhouse
            ),
            cwd=staged,
            env=environment,
            text=True,
            capture_output=True,
            timeout=600,
        )
        if install.returncode:
            return {
                "valid": False,
                "certified": False,
                "published": False,
                "run_id": run_id,
                "errors": [
                    f"offline release toolchain install failed: {install.stderr[-2000:]}"
                ],
            }
        toolchain = toolchain_identity(str(release_python))
        build = build_release_artifacts_once(
            staged,
            selected_artifact_dir,
            python_executable=str(release_python),
            environment=environment,
            intermediate_quarantine=directory / "build-intermediates",
        )
        if not build["valid"] or build["build_invocations"] != 1:
            return {
                "valid": False,
                "certified": False,
                "published": False,
                "run_id": run_id,
                "errors": build["errors"],
            }
        # Evidence produced while gates are still running is transaction state,
        # not part of the product being audited. Keep it in external custody so
        # repository-wide closed denominators cannot self-ingest an unfinished
        # release. It is copied into the canonical evidence tree only after every
        # gate and frozen-product check passes.
        release_root = directory / "release-evidence" / release
        evidence_dir = release_root / run_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        _dump(evidence_dir / "wheelhouse-manifest.json", wheelhouse_manifest)
        _dump(evidence_dir / "toolchain.json", toolchain)
        _dump(evidence_dir / "artifact-manifest.json", build["artifact_manifest"])
        if build.get("intermediate_custody") is not None:
            _dump(
                evidence_dir / "build-intermediate-custody.json",
                build["intermediate_custody"],
            )
        product_manifest = {
            key: frozen[key]
            for key in (
                "schema_version",
                "policy_version",
                "policy_sha256",
                "product_digest",
                "harness_digest",
                "product_records",
            )
        }
        _dump(evidence_dir / "product-manifest.json", product_manifest)
        supply_chain = _write_supply_chain_evidence(
            evidence_dir,
            release=release,
            source_control=source_control,
            product_digest=frozen["product_digest"],
            artifacts=build["artifacts"],
            toolchain=toolchain,
        )
        publication_plan = {
            "schema_version": "1.0",
            "status": "staged_exact_bytes",
            "release": release,
            "run_id": run_id,
            "source_control": source_control,
            "artifacts": build["artifacts"],
            "artifact_manifest_sha256": build["artifact_manifest_sha256"],
            "rebuild_allowed": False,
        }
        _dump(evidence_dir / "publication-plan.json", publication_plan)
        try:
            if gate_runner is run_release_gates:
                gates = gate_runner(
                    staged,
                    evidence_dir,
                    release_python=str(release_python),
                    artifact_dir=selected_artifact_dir,
                    artifact_records=build["artifacts"],
                    toolchain=toolchain,
                    wheelhouse_manifest=wheelhouse_manifest,
                    evidence_locator_prefix=f"evidence/releases/{release}/{run_id}",
                )
            else:
                gates = gate_runner(staged, evidence_dir)
        except Exception as error:
            gates = {
                "schema_version": "2.0",
                "valid": False,
                "errors": [f"gate runner failed: {type(error).__name__}: {error}"],
                "gates": {},
            }
            _dump(evidence_dir / "gate-summary.json", gates)
        if mutation_hook:
            mutation_hook()
        unchanged = verify_frozen_product(root, initial)
        staged_unchanged = verify_frozen_product(staged, frozen)
        if (
            not gates.get("valid")
            or not unchanged["valid"]
            or not staged_unchanged["valid"]
        ):
            gate_errors = list(gates.get("errors", []))
            if not gate_errors and isinstance(gates.get("gates"), dict):
                for gate_name, gate in gates["gates"].items():
                    if not isinstance(gate, dict) or gate.get("valid") is True:
                        continue
                    details = gate.get("errors")
                    if isinstance(details, list) and details:
                        gate_errors.extend(
                            f"{gate_name}: {detail}" for detail in details
                        )
                    else:
                        gate_errors.append(f"{gate_name}: failed")
            return {
                "valid": False,
                "certified": False,
                "published": False,
                "run_id": run_id,
                "artifact_dir": str(selected_artifact_dir),
                "errors": [
                    *gate_errors,
                    *unchanged["errors"],
                    *staged_unchanged["errors"],
                ],
                "gates": gates,
            }
        roles: dict[str, dict[str, object]] = {}
        for path in sorted(
            evidence_dir.rglob("*"), key=lambda item: item.as_posix().casefold()
        ):
            if path.is_file() and path.name != "evidence-manifest.json":
                relative = path.relative_to(evidence_dir).as_posix()
                roles[relative] = {
                    "type": path.suffix.casefold().lstrip(".") or "evidence",
                    "required": True,
                    "generation_gate": path.stem,
                    "producer": f"PACIFY-X {release}",
                }
        evidence_manifest = build_evidence_manifest(evidence_dir, roles=roles)
        _dump(evidence_dir / "evidence-manifest.json", evidence_manifest)
        certificate_relative = f"evidence/releases/{release}/certificate.json"
        signature_relative = f"evidence/releases/{release}/certificate.json.sig"
        certificate = {
            "schema_version": "3.0",
            "release": release,
            "status": "self_certified",
            "run_id": run_id,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source_control": source_control,
            "product_digest": frozen["product_digest"],
            "harness_digest": frozen["harness_digest"],
            "manifest_file_count": len(frozen["product_records"]),
            "artifact_policy_sha256": frozen["policy_sha256"],
            "artifacts": build["artifacts"],
            "evidence_manifest": f"evidence/releases/{release}/{run_id}/evidence-manifest.json",
            "evidence_manifest_sha256": _sha(evidence_dir / "evidence-manifest.json"),
            "gate_summary": f"evidence/releases/{release}/{run_id}/gate-summary.json",
            "coverage_evidence": f"evidence/releases/{release}/{run_id}/coverage.json",
            "coverage_evidence_sha256": _sha(evidence_dir / "coverage.json"),
            "toolchain": toolchain,
            "wheelhouse_manifest_sha256": wheelhouse_manifest["manifest_sha256"],
            "certification_platform": certification_platform_binding(toolchain),
            "artifact_manifest": f"evidence/releases/{release}/{run_id}/artifact-manifest.json",
            "artifact_manifest_sha256": build["artifact_manifest_sha256"],
            "publication_plan": f"evidence/releases/{release}/{run_id}/publication-plan.json",
            "supply_chain_evidence": {
                name: f"evidence/releases/{release}/{run_id}/{relative}"
                for name, relative in supply_chain.items()
            },
            "revocation_triggers": [
                "artifact hash mismatch",
                "evidence manifest mismatch",
                "Git identity mismatch",
                "product digest mismatch",
                "publisher signature failure",
                "signer revocation",
            ],
        }
        signature_path = release_root / "certificate.json.sig"
        certificate = sign_certificate(
            certificate, private_key=signing_key, signature_path=signature_path
        )
        _dump(release_root / "certificate.json", certificate)
        journal_path = root / ".engineering-bootstrap/release-transaction.json"
        journal = {
            "schema_version": "2.0",
            "run_id": run_id,
            "status": "publishing_evidence",
            "release": release,
            "product_digest": frozen["product_digest"],
            "certificate": certificate_relative,
            "signature": signature_relative,
            "hard_delete": False,
        }
        _dump(journal_path, journal)
        destination = root / "evidence" / "releases" / release
        evidence_commit = _commit_release_evidence(release_root, destination)
        if not evidence_commit["valid"]:
            return {
                "valid": False,
                "certified": False,
                "published": False,
                "run_id": run_id,
                "errors": evidence_commit["errors"],
            }
        journal["status"] = "evidence_committed"
        _dump(journal_path, journal)
    verification = verify_release_certificate(
        root, release=release, artifact_dir=selected_artifact_dir
    )
    return {
        "valid": verification["valid"],
        "certified": verification["valid"],
        "published": False,
        "run_id": run_id,
        "certificate": certificate_relative,
        "signature": signature_relative,
        "artifact_dir": str(selected_artifact_dir),
        "product_digest": frozen["product_digest"],
        "errors": verification["errors"],
    }


def verify_release_certificate(
    root: Path, *, release: str | None = None, artifact_dir: Path | None = None
) -> dict[str, Any]:
    root = root.resolve()
    release = release or authoritative_version(root)
    errors: list[str] = []
    revocation_path = root / f"evidence/release-revocation-{release}.json"
    if revocation_path.is_file():
        revocation = _json(revocation_path)
        if revocation.get("status") == "revoked":
            return {
                "valid": False,
                "release": release,
                "errors": [f"release {release} is explicitly revoked"],
            }
    certificate_path = root / "evidence" / "releases" / release / "certificate.json"
    if not certificate_path.is_file():
        return {
            "valid": False,
            "release": release,
            "errors": ["signed release certificate is missing"],
        }
    certificate = _json(certificate_path)
    if certificate.get("release") != release:
        errors.append("certificate release mismatch")
    if certificate.get("status") != "self_certified":
        errors.append("certificate status is not self_certified")
    platform_binding = certificate.get("certification_platform", {})
    if not isinstance(platform_binding, dict):
        errors.append("certificate platform binding is malformed")
    else:
        errors.extend(validate_certification_platform(root, platform_binding)["errors"])
    signature_name = (
        str(certificate.get("signature", {}).get("path", ""))
        if isinstance(certificate.get("signature"), dict)
        else ""
    )
    signature = verify_certificate_signature(
        certificate,
        signature_path=certificate_path.parent / signature_name,
        trust_policy_path=root / "policies/release-trust.json",
    )
    errors.extend(signature["errors"])
    versions = validate_version_surfaces(root, asserted=release)
    errors.extend(versions["errors"])
    source = verify_recorded_git_identity(
        root, dict(certificate.get("source_control", {}))
    )
    errors.extend(source["errors"])
    current = classify_tree(root)
    errors.extend(current["errors"])
    if current["product_digest"] != certificate.get("product_digest"):
        errors.append("current product digest does not match certificate")
    if current["harness_digest"] != certificate.get("harness_digest"):
        errors.append("current harness digest does not match certificate")
    coverage_binding = _verify_coverage_binding(root, release, certificate)
    errors.extend(coverage_binding["errors"])
    evidence_relative = str(certificate.get("evidence_manifest", ""))
    evidence_path = (root / evidence_relative).resolve(strict=False)
    if (
        not evidence_relative.startswith(f"evidence/releases/{release}/")
        or not evidence_path.is_file()
    ):
        errors.append(
            "certificate evidence manifest is missing or outside its release root"
        )
    else:
        if _sha(evidence_path) != certificate.get("evidence_manifest_sha256"):
            errors.append("certificate evidence-manifest file hash mismatch")
        else:
            manifest = _json(evidence_path)
            evidence_check = verify_evidence_manifest(evidence_path.parent, manifest)
            errors.extend(evidence_check["errors"])
    artifact_manifest_relative = str(certificate.get("artifact_manifest", ""))
    artifact_manifest_path = (root / artifact_manifest_relative).resolve(strict=False)
    if (
        not artifact_manifest_relative.startswith(f"evidence/releases/{release}/")
        or not artifact_manifest_path.is_file()
    ):
        errors.append(
            "certificate artifact manifest is missing or outside its release root"
        )
    else:
        artifact_manifest = _json(artifact_manifest_path)
        if artifact_manifest.get("manifest_sha256") != certificate.get(
            "artifact_manifest_sha256"
        ):
            errors.append(
                "recorded artifact manifest digest does not match certificate"
            )
    records = certificate.get("artifacts")
    if artifact_dir is None:
        errors.append("artifact directory is required to verify exact release bytes")
    elif not isinstance(records, list):
        errors.append("certificate artifact records are malformed")
    else:
        artifact_check = verify_artifact_records(artifact_dir, records)
        errors.extend(artifact_check["errors"])
        artifact_binding = bind_artifact_set(
            artifact_dir,
            records,
            source_product_digest=current["product_digest"],
            version=release,
            source_root=root,
        )
        errors.extend(artifact_binding["errors"])
        if artifact_binding.get("artifact_manifest_sha256") != certificate.get(
            "artifact_manifest_sha256"
        ):
            errors.append("artifact manifest digest does not match certificate")
    errors.extend(_certificate_ledger_errors(root))
    return {
        "valid": not errors,
        "release": release,
        "run_id": certificate.get("run_id"),
        "product_digest": current["product_digest"],
        "signing_identity": signature.get("identity"),
        "errors": errors,
    }
