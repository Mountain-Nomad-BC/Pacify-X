"""Atomic, clean-workspace, digest-bound release certification."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import nullcontext
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
from .artifact_reachability import build_artifact_reachability
from .exact_tool_certification import certify_exact_tools
from .file_lock import FileLock
from .generated_artifacts import validate_generated_artifacts
from .release_artifacts import classify_tree, verify_frozen_product


FINALIZER_CARDS = {"REL-010-C", "REL-010-E"}
MACHINE_LOCAL_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]|/(?:users|home|tmp|var/tmp)/)")
PROJECT_ESCAPE_PATH = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _junit_totals(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    tag = root.tag.rsplit("}", 1)[-1]
    if tag == "testsuite":
        suites = [root]
    else:
        suites = [item for item in list(root) if item.tag.rsplit("}", 1)[-1] == "testsuite"]
    return {
        name: sum(int(suite.attrib.get(name, 0)) for suite in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }


def _junit_case_gate(path: Path, marker: str) -> dict[str, Any]:
    """Require a named test surface to be present and entirely green."""
    root = ET.parse(path).getroot()
    cases = [
        case for case in root.iter("testcase")
        if marker in str(case.attrib.get("classname", "")) or marker in str(case.attrib.get("name", ""))
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


def _sanitize_junit_metadata(path: Path) -> None:
    """Remove host identity from otherwise useful public test evidence."""
    tree = ET.parse(path)
    for suite in tree.getroot().iter("testsuite"):
        suite.attrib.pop("hostname", None)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _junit_metadata_gate(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    hostnames = [suite.attrib["hostname"] for suite in root.iter("testsuite") if "hostname" in suite.attrib]
    paths = _portable_payload_gate(ET.tostring(root, encoding="unicode"))
    errors = [*("JUnit evidence contains host identity" for _ in hostnames), *paths["errors"]]
    return {
        "valid": not errors,
        "hostname_count": len(hostnames),
        "nonportable_path_count": paths["nonportable_path_count"],
        "errors": errors,
    }


def _release_environment_gate(root: Path, python_executable: str, environment: dict[str, str]) -> dict[str, Any]:
    process = subprocess.run(
        [python_executable, "-m", "runtime.cli", "--root", str(root), "release", "environment"],
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
            "errors": [f"isolated release environment produced invalid output: {process.stderr[-1000:]}"],
        }
    if process.returncode != 0 and result.get("valid") is True:
        result = {
            **result,
            "valid": False,
            "errors": [*result.get("errors", []), f"environment command exited {process.returncode}"],
        }
    return result


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(value)
    unsigned.pop("certificate_sha256", None)
    digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**unsigned, "certificate_sha256": digest}


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
        if card["priority"] not in {"P0", "P1"} and card["status"] not in {"passed", "rejected_with_evidence", "deferred_with_owner"}:
            errors.append(f"{card['id']}: nonblocking card lacks final disposition")
    return errors


def _stage_final_state(root: Path, release: str, certificate_relative: str) -> None:
    ledger_path = root / "registry/corrective_release_ledger.json"
    ledger = _json(ledger_path)
    for card in ledger["cards"]:
        if card["id"] in FINALIZER_CARDS:
            card["status"] = "passed"
            card["receipts"] = sorted(set([*card.get("receipts", ()), certificate_relative]))
            card["disposition"] = "Passed only through the atomic clean-workspace finalizer bound to the published product and harness digests."
        elif card["id"] == "TST-010-D":
            card["receipts"] = sorted(set([*card.get("receipts", ()), certificate_relative]))
            card["disposition"] = "The finalizer reran the complete staged-tree profile and bound its zero-failure result to the published product and harness digests."
    _dump(ledger_path, ledger)

    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8")
    text = re_sub_release(text, release)
    text = text.replace("**Status:** Certified deployment-ready", "**Status:** Certified deployment-ready")
    text = re_sub_line(text, "**Status:**", "**Status:** Certified deployment-ready  ")
    readme.write_text(text, encoding="utf-8", newline="\n")

    management_path = root / "PROJECT_MANAGEMENT.md"
    management = management_path.read_text(encoding="utf-8")
    management = re_sub_line(management, "Phase:", "Phase: `deployment certified`")
    management = re_sub_line(management, "Status:", "Status: `complete`")
    management = management.replace("Status: `active — deployment blocked`", "Status: `complete`")
    management = re_sub_line(management, "Active card:", "Active card: `none`")
    management = re_sub_line(management, "Next action:", f"Next action: deploy release {release}; any material product mutation revokes readiness until recertified.")
    start = management.index("## Corrective atomic-recertification card - REL-010")
    end = management.index("## Primary user entry points", start)
    management = management[:start] + management[start:end].replace("- [ ]", "- [x]") + management[end:]
    if f"Release evidence: `{certificate_relative}`." not in management[start:end]:
        insert = management.index("## Primary user entry points", start)
        management = management[:insert] + f"Release evidence: `{certificate_relative}`.\n\n" + management[insert:]
    management_path.write_text(management, encoding="utf-8", newline="\n")

    state_path = root / ".engineering-bootstrap/project-management/state.json"
    state = _json(state_path)
    next_action = f"deploy release {release}; any material product mutation revokes readiness until recertified"
    state["lifecycle"] = {"phase": "deployment-certified", "status": "complete", "next_action": next_action}
    state["work"]["active_punch_card"] = None
    for collection in (state["work"].get("milestones", ()), state["work"].get("backlog", ())):
        for item in collection:
            if str(item.get("id", "")).startswith("REL-010"):
                item["status"] = "complete"
    state["checkpoint"]["revision"] = int(state["checkpoint"].get("revision", 0)) + 1
    state["checkpoint"]["runtime_version"] = release
    state["checkpoint"]["validation"] = {"tests": "release_profile_passed", "verifier": f"release_{release}"}
    state["checkpoint"]["next_safe_action"] = next_action
    state["evidence"]["validation_receipt"] = certificate_relative
    _dump(state_path, state)

    # Finalizing the ledger changes a registry digest. Refresh its closed-world
    # ownership record inside the staged tree before freezing the product.
    _dump(root / "registry/artifact_reachability.json", build_artifact_reachability(root))


def re_sub_line(text: str, prefix: str, replacement: str) -> str:
    lines = text.splitlines()
    return "\n".join(replacement if line.startswith(prefix) else line for line in lines) + "\n"


def re_sub_release(text: str, release: str) -> str:
    import re
    return re.sub(r"(?m)^\*\*Current release:\*\* v[0-9]+\.[0-9]+\.[0-9]+\s*$", f"**Current release:** v{release}  ", text)


def run_release_gates(root: Path, evidence_dir: Path) -> dict[str, Any]:
    """Run every release gate against the isolated staged product tree."""
    started = time.monotonic()
    environment = dict(os.environ)
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"})
    environment_quarantine = Path(tempfile.gettempdir()) / "pacify-x-release-quarantine"
    environment_quarantine.mkdir(parents=True, exist_ok=True)
    environment_root = Path(tempfile.mkdtemp(prefix="environment-", dir=environment_quarantine))
    venv.EnvBuilder(with_pip=True).create(environment_root)
    release_python = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    install_started = time.monotonic()
    install = subprocess.run([str(release_python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(root / "requirements-release.lock")], cwd=root, env=environment, text=True, capture_output=True, timeout=600)
    toolchain_gate = {
        "valid": install.returncode == 0,
        "exit_code": install.returncode,
        "duration_seconds": round(time.monotonic() - install_started, 6),
        "stderr": install.stderr[-4000:],
        "custody_class": "external_temporary_quarantine",
        "custody_id": environment_root.name,
        "hard_delete": False,
    }
    from .test_profiles import resolve_test_profile
    profile = resolve_test_profile(root, "full")
    tests_started = time.monotonic()
    junit_path = evidence_dir / "full-tests.junit.xml"
    test_command = [str(release_python), *profile["command"][1:], f"--junitxml={junit_path}"]
    try:
        test_process = subprocess.run(test_command, cwd=root, env=environment, text=True, capture_output=True, timeout=profile["timeout_seconds"])
        test_stdout, test_stderr, test_exit, test_timed_out = test_process.stdout, test_process.stderr, test_process.returncode, False
    except subprocess.TimeoutExpired as error:
        test_stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
        test_stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
        test_exit, test_timed_out = None, True
    test_log = evidence_dir / "full-tests.log"
    test_log.parent.mkdir(parents=True, exist_ok=True)
    test_log.write_text(test_stdout + test_stderr, encoding="utf-8")
    if junit_path.is_file():
        _sanitize_junit_metadata(junit_path)
        totals = _junit_totals(junit_path)
    else:
        totals = {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}
    gates: dict[str, Any] = {
        "release_toolchain": toolchain_gate,
        "full_tests": {"valid": test_exit == 0 and not test_timed_out and totals["tests"] > 0 and totals["failures"] == totals["errors"] == totals["skipped"] == 0, "exit_code": test_exit, "timed_out": test_timed_out, "duration_seconds": round(time.monotonic() - tests_started, 6), "log": test_log.relative_to(root).as_posix(), **totals},
    }
    gates["installed_wheel"] = _junit_case_gate(junit_path, "test_installed_wheel_e2e") if junit_path.is_file() else {"valid": False, "tests": 0, "errors": 1, "marker": "test_installed_wheel_e2e"}
    gates["junit_metadata_portability"] = _junit_metadata_gate(junit_path) if junit_path.is_file() else {"valid": False, "hostname_count": 0, "nonportable_path_count": 0, "errors": ["JUnit evidence is missing"]}
    exact = certify_exact_tools(root, aggregate_timeout_seconds=1_200, receipt_path=evidence_dir / "exact-tools.json", allow_cache=False, python_executable=str(release_python))
    gates["exact_tools"] = {"valid": exact["valid"], "denominator": exact["admitted_tools"] + exact["domain_wrappers"], "passed": exact["passed_tools"] + exact["passed_domain_wrappers"], "duration_seconds": exact["duration_seconds"], "errors": exact["errors"]}
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
    from scripts.audit_sanitization import audit as audit_sanitization
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
        "corrective_release": validate_corrective_ledger(root, require_blocking_passed=True),
        "effect_surfaces": validate_effect_surfaces(root),
        "evidence_portability": validate_evidence_portability(root),
        "release_environment": _release_environment_gate(root, str(release_python), environment),
        "licensing": validate_licensing(root),
    }
    for name, result in checks.items():
        errors = list(result.get("errors", []))
        if not errors and isinstance(result.get("checks"), list):
            errors = [
                f"{item.get('id', 'unknown')}: {item.get('detail', 'failed')}"
                for item in result["checks"]
                if not item.get("passed", False)
            ]
        gates[name] = {"valid": bool(result.get("valid", result.get("complete", False))), "errors": errors}
    sanitation = audit_sanitization(root)
    gates["sanitization"] = {
        "valid": bool(sanitation["valid"]),
        "files_scanned": sanitation["files_scanned"],
        "identifier_hits": sanitation["identifier_hit_count"],
        "legacy_placeholder_hits": sanitation["legacy_placeholder_hit_count"],
        "active_zip_files": sanitation["active_zip_count"],
        "errors": sanitation["errors"],
    }
    build_started = time.monotonic()
    build_quarantine = Path(tempfile.gettempdir()) / "pacify-x-release-quarantine"
    build_quarantine.mkdir(parents=True, exist_ok=True)
    build_dir = Path(tempfile.mkdtemp(prefix="build-", dir=build_quarantine))
    try:
        build = subprocess.run([str(release_python), "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(build_dir)], cwd=root, env=environment, text=True, capture_output=True, timeout=300)
        build_exit, build_stderr, build_timed_out = build.returncode, build.stderr[-4000:], False
    except subprocess.TimeoutExpired as error:
        build_exit = None
        build_stderr = (error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else (error.stderr or ""))[-4000:]
        build_timed_out = True
    gates["clean_build"] = {
        "valid": build_exit == 0 and not build_timed_out and len(list(build_dir.iterdir())) == 2,
        "exit_code": build_exit,
        "timed_out": build_timed_out,
        "artifact_count": len(list(build_dir.iterdir())),
        "duration_seconds": round(time.monotonic() - build_started, 6),
        "stderr": build_stderr,
        "custody_class": "external_temporary_quarantine",
        "custody_id": build_dir.name,
        "hard_delete": False,
    }
    gates["publishable_evidence_portability"] = _portable_payload_gate(gates)
    valid = all(item["valid"] for item in gates.values())
    result = {"schema_version": "1.0", "valid": valid, "gate_count": len(gates), "gates": gates, "duration_seconds": round(time.monotonic() - started, 6)}
    _dump(evidence_dir / "gate-summary.json", result)
    return result


def _copy_clean(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".ruff_cache", "*.pyc", "*.pyo", "*.egg-info", "build", "dist", "release.lock", "release-transaction.json"))


def finalize_release(
    root: Path,
    release: str,
    *,
    gate_runner: Callable[[Path, Path], dict[str, Any]] = run_release_gates,
    mutation_hook: Callable[[], None] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    eligibility = _eligible_ledger(root)
    if eligibility:
        return {"valid": False, "published": False, "errors": eligibility}
    initial = classify_tree(root)
    if not initial["valid"]:
        return {"valid": False, "published": False, "errors": initial["errors"]}
    run_id = f"rel-{release}-{uuid.uuid4().hex[:12]}"
    certificate_relative = f"evidence/release-certification-{release}.json"
    lock_path = root / ".engineering-bootstrap/release.lock"
    with FileLock(lock_path, timeout_seconds=0.25):
        release_quarantine = Path(tempfile.gettempdir()) / "pacify-x-release-quarantine"
        release_quarantine.mkdir(parents=True, exist_ok=True)
        with nullcontext(tempfile.mkdtemp(prefix="workspace-", dir=release_quarantine)) as directory:
            staged = Path(directory) / "product"
            _copy_clean(root, staged)
            _stage_final_state(staged, release, certificate_relative)
            _dump(staged / certificate_relative, {"schema_version": "2.0", "release": release, "status": "staging", "run_id": run_id})
            frozen = classify_tree(staged)
            if not frozen["valid"]:
                return {"valid": False, "published": False, "errors": frozen["errors"]}
            evidence_dir = staged / "evidence/release-runs" / run_id
            try:
                gates = gate_runner(staged, evidence_dir)
            except Exception as error:
                gates = {"schema_version": "1.0", "valid": False, "errors": [f"gate runner failed: {type(error).__name__}: {error}"], "gates": {}}
                _dump(evidence_dir / "gate-summary.json", gates)
            if mutation_hook:
                mutation_hook()
            unchanged = verify_frozen_product(root, initial)
            if not gates.get("valid") or not unchanged["valid"]:
                return {"valid": False, "published": False, "run_id": run_id, "errors": [*gates.get("errors", []), *unchanged["errors"]], "gates": gates}
            # The gate runner may create only excluded evidence/intermediate files.
            staged_check = verify_frozen_product(staged, frozen)
            if not staged_check["valid"]:
                return {"valid": False, "published": False, "run_id": run_id, "errors": staged_check["errors"], "gates": gates}
            certificate = _seal({
                "schema_version": "2.0", "release": release, "status": "deployment_ready", "run_id": run_id,
                "created_utc": datetime.now(timezone.utc).isoformat(), "product_digest": frozen["product_digest"],
                "harness_digest": frozen["harness_digest"], "manifest_file_count": len(frozen["product_records"]),
                "artifact_policy_sha256": frozen["policy_sha256"], "gate_summary": f"evidence/release-runs/{run_id}/gate-summary.json",
                "publication_receipt": f"evidence/release-runs/{run_id}/publication-receipt.json",
                "gates": gates, "revocation_triggers": ["product digest mismatch", "harness digest mismatch", "certificate seal mismatch", "project state not deployment-certified"],
            })
            _dump(staged / certificate_relative, certificate)
            manifest_path = evidence_dir / "product-manifest.json"
            _dump(manifest_path, {key: frozen[key] for key in ("schema_version", "policy_version", "policy_sha256", "product_digest", "harness_digest", "product_records")})
            projections = [
                "registry/corrective_release_ledger.json",
                "registry/artifact_reachability.json",
                "README.md",
                "PROJECT_MANAGEMENT.md",
                ".engineering-bootstrap/project-management/state.json",
            ]
            evidence_files = sorted(path for path in evidence_dir.rglob("*") if path.is_file()) + [staged / certificate_relative]
            journal_path = root / ".engineering-bootstrap/release-transaction.json"
            journal = {"schema_version": "1.0", "run_id": run_id, "status": "publishing", "release": release, "product_digest": frozen["product_digest"], "paths": projections, "hard_delete": False}
            _dump(journal_path, journal)
            for source in evidence_files:
                destination = root / source.relative_to(staged)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            # Publish machine state last; a partial transaction therefore remains blocked.
            for relative in projections:
                source = staged / relative
                destination = root / relative
                temporary = destination.with_name(destination.name + ".tmp")
                shutil.copy2(source, temporary)
                os.replace(temporary, destination)
            journal["status"] = "committed"
            journal["certificate"] = certificate_relative
            _dump(journal_path, journal)
            publication_receipt = _seal({
                "schema_version": "1.0",
                "status": "committed",
                "release": release,
                "run_id": run_id,
                "product_digest": frozen["product_digest"],
                "release_certificate": certificate_relative,
                "release_certificate_sha256": certificate["certificate_sha256"],
            })
            _dump(root / certificate["publication_receipt"], publication_receipt)
    verification = verify_release_certificate(root, release=release)
    return {"valid": verification["valid"], "published": verification["valid"], "run_id": run_id, "certificate": certificate_relative, "product_digest": frozen["product_digest"], "errors": verification["errors"]}


def verify_release_certificate(root: Path, *, release: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    state = _json(root / ".engineering-bootstrap/project-management/state.json")
    receipt = state.get("evidence", {}).get("validation_receipt")
    errors = []
    if state.get("lifecycle", {}).get("status") != "complete" or state.get("lifecycle", {}).get("phase") != "deployment-certified":
        errors.append("project state is not deployment-certified")
    if not isinstance(receipt, str) or not receipt.startswith("evidence/release-certification-"):
        errors.append("project state does not identify a release certificate")
        return {"valid": False, "errors": errors}
    certificate_path = root / receipt
    if not certificate_path.is_file():
        errors.append("release certificate is missing")
        return {"valid": False, "errors": errors}
    certificate = _json(certificate_path)
    portability = _portable_payload_gate(certificate)
    errors.extend(portability["errors"])
    if certificate.get("certificate_sha256") != _seal(certificate).get("certificate_sha256"):
        errors.append("certificate seal mismatch")
    if certificate.get("status") != "deployment_ready":
        errors.append("certificate status is not deployment_ready")
    if release is not None and certificate.get("release") != release:
        errors.append("certificate release mismatch")
    current = classify_tree(root)
    errors.extend(current["errors"])
    if current["product_digest"] != certificate.get("product_digest"):
        errors.append("current product digest does not match certificate")
    if current["harness_digest"] != certificate.get("harness_digest"):
        errors.append("current harness digest does not match certificate")
    publication_relative = certificate.get("publication_receipt")
    expected_publication = f"evidence/release-runs/{certificate.get('run_id')}/publication-receipt.json"
    if publication_relative != expected_publication:
        errors.append("certificate does not identify its durable publication receipt")
    else:
        publication_path = root / publication_relative
        if not publication_path.is_file():
            errors.append("durable publication receipt is missing")
        else:
            publication = _json(publication_path)
            if publication.get("certificate_sha256") != _seal(publication).get("certificate_sha256"):
                errors.append("durable publication receipt seal mismatch")
            if (
                publication.get("status") != "committed"
                or publication.get("run_id") != certificate.get("run_id")
                or publication.get("release") != certificate.get("release")
                or publication.get("product_digest") != certificate.get("product_digest")
                or publication.get("release_certificate") != receipt
                or publication.get("release_certificate_sha256") != certificate.get("certificate_sha256")
            ):
                errors.append("durable publication receipt does not match the release certificate")
    transaction_path = root / ".engineering-bootstrap/release-transaction.json"
    if transaction_path.is_file():
        transaction = _json(transaction_path)
        if transaction.get("status") != "committed" or transaction.get("run_id") != certificate.get("run_id"):
            errors.append("release transaction is incomplete or belongs to another run")
    ledger = validate_corrective_ledger(root, require_blocking_passed=True)
    if not ledger["valid"]:
        errors.extend(ledger["errors"])
    return {"valid": not errors, "release": certificate.get("release"), "run_id": certificate.get("run_id"), "product_digest": current["product_digest"], "errors": errors}
