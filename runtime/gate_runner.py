"""Independent, hash-keyed assurance gates with current-receipt finalization."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class GateSpec:
    gate_id: str
    inputs: tuple[str, ...]
    dependencies: tuple[str, ...]
    runner: Callable[[Path], dict[str, Any]]


def _registry(root: Path) -> dict[str, Any]:
    from .registry import validate_registry

    return validate_registry(root)


def _contracts(root: Path) -> dict[str, Any]:
    from .contracts import validate_contract_corpus

    return validate_contract_corpus(root)


def _structural(root: Path) -> dict[str, Any]:
    from .structural_integrity import audit_structural_integrity

    return audit_structural_integrity(root)


def _licensing(root: Path) -> dict[str, Any]:
    from .licensing import validate_licensing

    return validate_licensing(root)


def _generated(root: Path) -> dict[str, Any]:
    from .generated_artifacts import validate_generated_artifacts

    return validate_generated_artifacts(root)


def _dependencies(root: Path) -> dict[str, Any]:
    from .dependency_audit import validate_dependency_closure

    return validate_dependency_closure(root)


def _platform(root: Path) -> dict[str, Any]:
    from .release_environment import validate_support_matrix

    return validate_support_matrix(root)


def _lint(root: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "ruff", "check", "--no-cache", "."]
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    return {
        "valid": completed.returncode == 0,
        "command": "python -m ruff check --no-cache .",
        "exit_code": completed.returncode,
        "output": output,
        "cache_disabled": True,
        "errors": [] if completed.returncode == 0 else [output or "Ruff failed"],
    }


GATES = {
    spec.gate_id: spec
    for spec in (
        GateSpec(
            "contracts",
            (
                "contracts/**/*.json",
                "runtime/contracts.py",
                "registry/contract_ownership.json",
            ),
            (),
            _contracts,
        ),
        GateSpec(
            "dependencies",
            (
                "pyproject.toml",
                "requirements-release.lock",
                "runtime/dependency_audit.py",
                "registry/python_dependency_ownership.json",
                ".github/workflows/*.yml",
            ),
            (),
            _dependencies,
        ),
        GateSpec(
            "platform",
            (
                "policies/platform-support.json",
                "pyproject.toml",
                "runtime/platform_support.py",
                "runtime/release_environment.py",
                ".github/workflows/ci.yml",
            ),
            (),
            _platform,
        ),
        GateSpec(
            "lint",
            (
                "pyproject.toml",
                "runtime/**/*.py",
                "builders/**/*.py",
                "scripts/**/*.py",
                "tests/**/*.py",
                ".px/skills/**/scripts/*.py",
                "templates/**/*.py",
            ),
            (),
            _lint,
        ),
        GateSpec(
            "generated",
            (
                "runtime/**/*.py",
                "scripts/**/*.py",
                "registry/**/*.json",
                "registry/*.toml",
                "contracts/**/*.json",
                ".px/skills/**/SKILL.md",
                "pyproject.toml",
            ),
            ("contracts",),
            _generated,
        ),
        GateSpec(
            "registry",
            (
                "runtime/**/*.py",
                "registry/**/*.json",
                "registry/*.toml",
                "bootstrap/startup.toml",
                "contracts/**/*.json",
                ".px/skills/**/SKILL.md",
            ),
            ("contracts", "generated"),
            _registry,
        ),
        GateSpec(
            "licensing",
            (
                "LICENSE",
                "NOTICE",
                "README.md",
                "pyproject.toml",
                "policies/release-artifact-policy.json",
                "registry/skills/*.json",
            ),
            (),
            _licensing,
        ),
        GateSpec(
            "structural",
            (
                "README.md",
                "START_HERE_FOR_AI.md",
                "PROJECT_MANAGEMENT.md",
                "SECURITY.md",
                "CHANGELOG.md",
                "docs/**/*.md",
                "bootstrap/**/*",
                ".engineering-bootstrap/**/*.json",
                "policies/**/*.json",
                "runtime/**/*.py",
                "scripts/**/*.py",
                "tests/**/*.py",
                "contracts/**/*.json",
                "registry/**/*",
                ".px/skills/**/SKILL.md",
                "pyproject.toml",
            ),
            ("contracts", "generated", "registry"),
            _structural,
        ),
    )
}


def _matching_files(root: Path, patterns: Iterable[str]) -> list[Path]:
    files: dict[str, Path] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(root).as_posix()] = path
    return [files[key] for key in sorted(files)]


def _input_digest(
    root: Path, spec: GateSpec, dependency_receipts: Iterable[dict[str, Any]]
) -> str:
    digest = hashlib.sha256()
    digest.update(b"pacify-x-independent-gate/1.0\0")
    digest.update(spec.gate_id.encode())
    for path in _matching_files(root, spec.inputs):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    for receipt in dependency_receipts:
        digest.update(str(receipt.get("receipt_sha256", "")).encode())
    return digest.hexdigest()


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(value)
    unsigned.pop("receipt_sha256", None)
    payload = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    return {**unsigned, "receipt_sha256": hashlib.sha256(payload).hexdigest()}


def _load_receipt(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return (
            value
            if _seal(value).get("receipt_sha256") == value.get("receipt_sha256")
            else None
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def run_gates(
    root: Path,
    receipt_dir: Path,
    selected: Iterable[str] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    receipt_dir = receipt_dir.resolve()
    receipt_dir.mkdir(parents=True, exist_ok=True)
    requested = tuple(dict.fromkeys(selected or GATES))
    unknown = sorted(set(requested) - set(GATES))
    if unknown:
        return {
            "valid": False,
            "errors": ["unknown gates: " + ", ".join(unknown)],
            "results": [],
        }
    completed: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    def run_one(gate_id: str) -> dict[str, Any]:
        if gate_id in completed:
            return completed[gate_id]
        spec = GATES[gate_id]
        dependencies = [run_one(item) for item in spec.dependencies]
        digest = _input_digest(root, spec, dependencies)
        path = receipt_dir / f"{gate_id}.json"
        prior = _load_receipt(path)
        if (
            not force
            and prior
            and prior.get("input_sha256") == digest
            and prior.get("passed") is True
        ):
            receipt = prior
            state = "reused_current_pass"
        else:
            if any(not item.get("passed") for item in dependencies):
                result = {"valid": False, "errors": ["dependency gate failed"]}
            else:
                try:
                    result = spec.runner(root)
                except Exception as error:  # assurance boundary must produce a receipt
                    result = {
                        "valid": False,
                        "errors": [f"{type(error).__name__}: {error}"],
                    }
            receipt = _seal(
                {
                    "schema_version": "1.0",
                    "gate": gate_id,
                    "input_sha256": digest,
                    "dependencies": [
                        {"gate": item["gate"], "receipt_sha256": item["receipt_sha256"]}
                        for item in dependencies
                    ],
                    "passed": result.get("valid") is True,
                    "result": result,
                }
            )
            path.write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
            state = "executed"
        completed[gate_id] = receipt
        results.append(
            {
                "gate": gate_id,
                "passed": receipt["passed"],
                "state": state,
                "receipt": path.as_posix(),
                "receipt_sha256": receipt["receipt_sha256"],
            }
        )
        return receipt

    for gate_id in requested:
        run_one(gate_id)
    return {
        "valid": all(item["passed"] for item in results),
        "requested": list(requested),
        "results": results,
        "errors": [],
    }


def finalize_gates(root: Path, receipt_dir: Path) -> dict[str, Any]:
    """Require a current passing receipt for every registered gate without executing it."""
    root = root.resolve()
    receipt_dir = receipt_dir.resolve()
    receipts: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for gate_id, spec in GATES.items():
        dependencies = [
            receipts[item] for item in spec.dependencies if item in receipts
        ]
        path = receipt_dir / f"{gate_id}.json"
        receipt = _load_receipt(path)
        expected = _input_digest(root, spec, dependencies)
        if receipt is None:
            errors.append(f"{gate_id}: missing or invalid receipt")
        elif receipt.get("input_sha256") != expected:
            errors.append(f"{gate_id}: receipt is stale")
        elif receipt.get("passed") is not True:
            errors.append(f"{gate_id}: gate did not pass")
        else:
            receipts[gate_id] = receipt
    return {
        "valid": not errors,
        "gate_count": len(GATES),
        "current_passes": len(receipts),
        "errors": errors,
    }
