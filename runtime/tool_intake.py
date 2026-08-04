"""Fail-closed project tooling inventory and optional external scanner adapters."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable, Iterable

from .contracts import validate_instance


MANIFESTS = {
    "pyproject.toml": "python", "requirements.txt": "python", "requirements-dev.txt": "python",
    "package.json": "node", "package-lock.json": "node", "npm-shrinkwrap.json": "node",
    "pnpm-lock.yaml": "node", "yarn.lock": "node", "Cargo.toml": "rust", "Cargo.lock": "rust",
    "go.mod": "go", "go.sum": "go", "Dockerfile": "container", "compose.yaml": "container",
    "compose.yml": "container", ".vscode/extensions.json": "editor",
}
SUSPICIOUS = re.compile(r"(?i)(curl\s|wget\s|invoke-webrequest|powershell\s+-enc|\beval\s*\(|base64\s+-d|chmod\s+\+x|postinstall|preinstall)")
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    return resolved == root.resolve() or root.resolve() in resolved.parents


def _corpus_digest(project: Path) -> str:
    records = []
    for path in sorted(project.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_file() and not path.is_symlink() and _inside(path, project):
            records.append((path.relative_to(project).as_posix(), path.stat().st_size, _sha(path)))
    return hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()


def execute_scanner(
    command: list[str], *, project: Path, approved_executable: Path,
    corpus_digest: str, network_allowed: bool | None = None,
    network_isolation_enforced: bool = False, timeout_seconds: int = 300,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Run a pre-authorized scanner with a minimal environment and bound result."""
    if timeout_seconds < 1:
        raise ValueError("scanner timeout must be positive")
    if not re.fullmatch(r"[0-9a-f]{64}", corpus_digest):
        raise ValueError("scanner corpus digest must be a lowercase SHA-256")
    if network_allowed is None:
        raise PermissionError("scanner network policy must be explicit")
    if network_allowed is False and not network_isolation_enforced:
        raise PermissionError("network-denied scanner requires an enforced isolation adapter")
    executable = approved_executable.resolve(strict=True)
    if not executable.is_file() or not os.path.isabs(str(approved_executable)):
        raise PermissionError("scanner executable must be an absolute regular file")
    if not command or not Path(command[0]).is_absolute():
        raise PermissionError("scanner path shadowing or identity mismatch")
    try:
        command_executable = Path(command[0]).resolve(strict=True)
    except OSError as error:
        raise PermissionError("scanner path shadowing or identity mismatch") from error
    if command_executable != executable:
        raise PermissionError("scanner path shadowing or identity mismatch")
    environment = {
        "PATH": str(executable.parent), "NO_COLOR": "1", "PYTHONNOUSERSITE": "1",
    }
    for name in ("SYSTEMROOT", "WINDIR", "COMSPEC"):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    environment["ENGINEERING_BOOTSTRAP_NETWORK"] = "allow" if network_allowed else "deny"
    try:
        version_result = runner(
            [str(executable), "--version"], cwd=project.resolve(), capture_output=True,
            text=True, timeout=min(timeout_seconds, 15), shell=False, env=environment,
        )
        if version_result.returncode:
            return {
                "status": "failure", "failure_stage": "scanner_identity",
                "scanner": {"path": executable.as_posix(), "sha256": _sha(executable), "version": None},
                "input_corpus_sha256": corpus_digest, "network_allowed": network_allowed,
                "network_isolation_enforced": network_isolation_enforced,
            }
        version = ((version_result.stdout or version_result.stderr or "").strip().splitlines() or [""])[0][:500]
        if not version:
            return {
                "status": "failure", "failure_stage": "scanner_identity",
                "scanner": {"path": executable.as_posix(), "sha256": _sha(executable), "version": None},
                "input_corpus_sha256": corpus_digest, "network_allowed": network_allowed,
                "network_isolation_enforced": network_isolation_enforced,
            }
        completed = runner(command, cwd=project.resolve(), capture_output=True, text=True, timeout=timeout_seconds, shell=False, env=environment)
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout", "scanner": {"path": executable.as_posix(), "sha256": _sha(executable), "version": None},
            "input_corpus_sha256": corpus_digest, "network_allowed": network_allowed,
            "network_isolation_enforced": network_isolation_enforced,
        }
    output = (completed.stdout or "") + (completed.stderr or "")
    parse_error = None
    try:
        structured = json.loads(completed.stdout or "")
    except json.JSONDecodeError as error:
        structured = None
        parse_error = f"{type(error).__name__}: scanner stdout is not structured JSON"
    status = "pass" if completed.returncode == 0 and parse_error is None else "failure"
    return {
        "status": status, "failure_stage": "structured_output" if parse_error else ("scanner_execution" if completed.returncode else None),
        "returncode": completed.returncode, "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "output_bytes": len(output.encode()), "structured_output_type": type(structured).__name__ if structured is not None else None,
        "parse_error": parse_error,
        "scanner": {"path": executable.as_posix(), "sha256": _sha(executable), "version": version},
        "network_allowed": network_allowed, "network_isolation_enforced": network_isolation_enforced,
        "input_corpus_sha256": corpus_digest,
    }


def _inventory(project: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative, ecosystem in MANIFESTS.items():
        path = project / relative
        if not path.is_file():
            continue
        if not _inside(path, project) or path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError(f"manifest is outside scope or too large: {relative}")
        text = path.read_text(encoding="utf-8", errors="replace")
        indicators = sorted(set(match.group(0).strip() for match in SUSPICIOUS.finditer(text)))
        records.append({
            "component_id": relative.replace("/", "-").replace(".", "-"),
            "source": relative,
            "ecosystem": ecosystem,
            "sha256": _sha(path),
            "bytes": path.stat().st_size,
            "license": "UNKNOWN",
            "permissions": ["read_project_manifest"],
            "vulnerabilities": [],
            "malicious_indicators": indicators,
            "policy_compatible": False,
            "approval": False,
        })
    return records


def _recipes(ecosystems: set[str], project: Path) -> list[tuple[str, list[str]]]:
    recipes: list[tuple[str, list[str]]] = []
    if "node" in ecosystems and (project / "package-lock.json").is_file():
        recipes.append(("npm-audit", ["npm", "audit", "--json", "--ignore-scripts"]))
    if "python" in ecosystems and shutil.which("pip-audit"):
        recipes.append(("pip-audit", ["pip-audit", "--format", "json", "--local"]))
    if "rust" in ecosystems and shutil.which("cargo-audit"):
        recipes.append(("cargo-audit", ["cargo", "audit", "--json"]))
    if shutil.which("trivy"):
        recipes.append(("trivy", ["trivy", "fs", "--format", "json", "--scanners", "vuln,secret,misconfig", "."]))
    if shutil.which("syft"):
        recipes.append(("syft-sbom-license", ["syft", ".", "-o", "json"]))
    if shutil.which("clamscan"):
        recipes.append(("clamav", ["clamscan", "--recursive", "--infected", "."]))
    return recipes


def scan_project_tooling(
    project: Path,
    framework_root: Path,
    *,
    execute_scanners: bool = False,
    scanner_approval: bool = False,
    scanner_network_allowed: bool | None = None,
    scanner_network_isolation_enforced: bool = False,
    component_approval: bool = False,
    allowed_licenses: Iterable[str] = (),
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    project = project.resolve()
    if not project.is_dir():
        raise ValueError("project root does not exist")
    components = _inventory(project)
    allowed = {value.casefold() for value in allowed_licenses}
    recipes = _recipes({item["ecosystem"] for item in components}, project)
    scanners: list[dict[str, Any]] = []
    if execute_scanners and not scanner_approval:
        raise PermissionError("external scanner execution requires explicit scanner approval")
    if execute_scanners and scanner_network_allowed is None:
        raise PermissionError("external scanner execution requires an explicit network policy")
    if execute_scanners:
        corpus_digest = _corpus_digest(project)
        for scanner_id, command in recipes:
            executable = shutil.which(command[0])
            if not executable:
                scanners.append({"id": scanner_id, "status": "unavailable", "command": command})
                continue
            try:
                result = execute_scanner(
                    [str(Path(executable).resolve()), *command[1:]], project=project,
                    approved_executable=Path(executable), corpus_digest=corpus_digest,
                    network_allowed=scanner_network_allowed,
                    network_isolation_enforced=scanner_network_isolation_enforced,
                    runner=runner,
                )
                scanners.append({"id": scanner_id, "command": command, **result})
            except (OSError, PermissionError) as error:
                scanners.append({"id": scanner_id, "status": "failure", "command": command, "error": type(error).__name__})
    else:
        scanners = [{"id": name, "status": "available_not_run", "command": command} for name, command in recipes]
    scanner_pass = bool(scanners) and all(item["status"] == "pass" for item in scanners)
    schema = framework_root / "contracts" / "external-tool-intake.schema.json"
    for item in components:
        item["approval"] = component_approval
        item["policy_compatible"] = (
            component_approval and scanner_pass and not item["malicious_indicators"]
            and item["license"].casefold() in allowed
        )
        validate_instance(item, schema)
    decision = "no_external_tooling" if not components else (
        "admit" if components and all(item["policy_compatible"] for item in components) else "quarantine"
    )
    return {
        "schema_version": "1.0", "project": project.as_posix(), "decision": decision,
        "execution_allowed": decision == "admit", "components": components, "scanners": scanners,
        "scanner_execution": "approved_and_executed" if execute_scanners else "not_executed",
        "limitations": [
            "UNKNOWN licenses require a reviewed license decision before admission.",
            "Unavailable or unexecuted scanners never produce an admission decision.",
            "This control does not execute, install, import, or detonate candidate packages.",
        ],
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


def record_tool_intake(project: Path, framework_root: Path, *, apply: bool = False, **scan_options: Any) -> dict[str, Any]:
    record = scan_project_tooling(project, framework_root, **scan_options)
    project_root = project.resolve()
    target_root = project_root / ".engineering-bootstrap" / "project-management"
    target = target_root / "tool-intake.json"
    if not apply:
        return {**record, "applied": False, "approval_required": True, "target": target.as_posix()}
    state_path = target_root / "state.json"
    if not state_path.is_file():
        raise ValueError("project must be commissioned before tool intake is recorded")
    target_root.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, indent=2) + "\n").encode()
    if target.is_file():
        history = target_root / "history" / f"tool-intake-{_sha(target)[:16]}.json"
        history.parent.mkdir(parents=True, exist_ok=True)
        if not history.exists():
            history.write_bytes(target.read_bytes())
    temporary = target.with_suffix(".json.next")
    temporary.write_bytes(payload)
    os.replace(temporary, target)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.setdefault("evidence", {})["tool_intake_records"] = [target.relative_to(project_root).as_posix()]
    state["checkpoint"]["revision"] = int(state["checkpoint"]["revision"]) + 1
    prior = target_root / "history" / f"state-{_sha(state_path)[:16]}.json"
    prior.parent.mkdir(parents=True, exist_ok=True)
    if not prior.exists():
        prior.write_bytes(state_path.read_bytes())
    state_next = state_path.with_suffix(".json.next")
    state_next.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(state_next, state_path)
    return {**record, "applied": True, "target": target.as_posix()}
