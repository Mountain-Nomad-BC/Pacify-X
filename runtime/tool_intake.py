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
    if execute_scanners:
        for scanner_id, command in recipes:
            executable = shutil.which(command[0])
            if not executable:
                scanners.append({"id": scanner_id, "status": "unavailable", "command": command})
                continue
            try:
                completed = runner(
                    [executable, *command[1:]], cwd=project, capture_output=True, text=True,
                    timeout=300, shell=False, env={**os.environ, "NO_COLOR": "1"},
                )
                combined = (completed.stdout or "") + (completed.stderr or "")
                scanners.append({
                    "id": scanner_id, "status": "pass" if completed.returncode == 0 else "findings_or_failure",
                    "returncode": completed.returncode, "output_sha256": hashlib.sha256(combined.encode()).hexdigest(),
                    "output_bytes": len(combined.encode()), "command": command,
                })
            except subprocess.TimeoutExpired:
                scanners.append({"id": scanner_id, "status": "timeout", "command": command})
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
    target_root = project.resolve() / ".engineering-bootstrap" / "project-management"
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
    state.setdefault("evidence", {})["tool_intake_records"] = [target.relative_to(project).as_posix()]
    state["checkpoint"]["revision"] = int(state["checkpoint"]["revision"]) + 1
    prior = target_root / "history" / f"state-{_sha(state_path)[:16]}.json"
    prior.parent.mkdir(parents=True, exist_ok=True)
    if not prior.exists():
        prior.write_bytes(state_path.read_bytes())
    state_next = state_path.with_suffix(".json.next")
    state_next.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(state_next, state_path)
    return {**record, "applied": True, "target": target.as_posix()}
