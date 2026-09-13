"""Independent, hash-keyed assurance gates with current-receipt finalization."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterable

from .repository_scope import is_external_environment_relative
from .verification_inputs import CapturedInputs


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
                "requirements-release.txt",
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


def _captured_gate_inputs(root: Path, spec: GateSpec) -> tuple[CapturedInputs, list[str]]:
    """Capture the gate's complete local dependency closure in one source image."""
    capture = CapturedInputs(root)
    direct = [
        relative
        for relative in capture.match(spec.inputs)
        if "__pycache__" not in Path(relative).parts
        and not is_external_environment_relative(Path(relative))
    ]
    if not direct:
        raise ValueError(f"independent gate {spec.gate_id} has an empty input denominator")
    members = capture.closure(direct)
    capture.verify()
    return capture, members


def _input_digest(
    root: Path, spec: GateSpec, dependency_receipts: Iterable[dict[str, Any]]
) -> str:
    digest, _members = _input_identity(root, spec, dependency_receipts)
    return digest


def _input_identity(
    root: Path, spec: GateSpec, dependency_receipts: Iterable[dict[str, Any]]
) -> tuple[str, list[str]]:
    capture, members = _captured_gate_inputs(root, spec)
    digest = hashlib.sha256()
    digest.update(b"pacify-x-independent-gate/2.0\0")
    digest.update(spec.gate_id.encode())
    for relative in members:
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(capture.digests[relative])
    for receipt in dependency_receipts:
        digest.update(str(receipt.get("receipt_sha256", "")).encode())
    return digest.hexdigest(), members


def _authority_path(root: Path) -> Path:
    configured = os.environ.get("PACIFY_X_GATE_AUTHORITY_ROOT")
    if configured:
        authority_root = Path(configured)
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        authority_root = Path(os.environ["LOCALAPPDATA"]) / "Pacify-X" / "gate-authority"
    else:
        authority_root = Path.home() / ".local" / "state" / "pacify-x" / "gate-authority"
    project_id = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
    return authority_root / f"{project_id}.authority"


def _protect_authority_key(value: bytes) -> bytes:
    return b"PXGA1\0HEX\0" + value.hex().encode("ascii")


def _unprotect_authority_key(value: bytes) -> bytes:
    if not value.startswith(b"PXGA1\0HEX\0"):
        return b""
    try:
        return bytes.fromhex(value[10:].decode("ascii"))
    except (UnicodeError, ValueError):
        return b""


def _read_authority_key(path: Path) -> bytes:
    value = b""
    for attempt in range(20):
        raw = path.read_bytes()
        try:
            value = _unprotect_authority_key(raw)
        except OSError:
            value = b""
        if len(value) == 32:
            return value
        if attempt < 19:
            time.sleep(0.005)
    return value


_AUTHORITY_LOCK = threading.RLock()
_AUTHORITY_KEYS: dict[Path, tuple[str, bytes]] = {}


def _authority_key_unlocked(root: Path, *, create: bool) -> bytes | None:
    path = _authority_path(root)
    try:
        value = _read_authority_key(path)
    except FileNotFoundError:
        if not create:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        value = os.urandom(32)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{value.hex()[:16]}.prepared")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            protected = _protect_authority_key(value)
            written = 0
            while written < len(protected):
                written += os.write(descriptor, protected[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            # Publish only a complete key. A hard-link is an exclusive atomic
            # create on both supported host families, so no reader can observe
            # the zero-length interval of O_EXCL followed by write.
            os.link(temporary, path)
        except FileExistsError:
            value = _read_authority_key(path)
        finally:
            temporary.unlink(missing_ok=True)
    if len(value) != 32:
        raise ValueError("independent gate receipt authority key is invalid")
    return value


def _authority_key(root: Path, *, create: bool) -> bytes | None:
    path = _authority_path(root)
    with _AUTHORITY_LOCK:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = None
        if raw is not None:
            cached = _AUTHORITY_KEYS.get(path)
            raw_digest = hashlib.sha256(raw).hexdigest()
            if cached is not None and cached[0] == raw_digest:
                return cached[1]
        value = _authority_key_unlocked(root, create=create)
        if value is not None:
            raw = path.read_bytes()
            _AUTHORITY_KEYS[path] = (hashlib.sha256(raw).hexdigest(), value)
        return value


def _seal(value: dict[str, Any], key: bytes | None = None) -> dict[str, Any]:
    unsigned = dict(value)
    unsigned.pop("receipt_sha256", None)
    payload = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(payload).hexdigest()
    sealed = {**unsigned, "receipt_sha256": digest}
    if key is not None:
        sealed["authority_hmac_sha256"] = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return sealed


def _load_receipt(path: Path, key: bytes | None) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if key is None or not isinstance(value, dict):
            return None
        authority = value.pop("authority_hmac_sha256", None)
        expected = _seal(value, key)
        return value | {"authority_hmac_sha256": authority} if (
            hmac.compare_digest(str(expected["receipt_sha256"]), str(value.get("receipt_sha256", "")))
            and hmac.compare_digest(str(expected["authority_hmac_sha256"]), str(authority or ""))
        ) else None
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
    authority_key = _authority_key(root, create=True)
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
        digest, members = _input_identity(root, spec, dependencies)
        path = receipt_dir / f"{gate_id}.json"
        prior = _load_receipt(path, authority_key)
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
                    "schema_version": "2.0",
                    "gate": gate_id,
                    "input_sha256": digest,
                    "input_count": len(members),
                    "input_members_sha256": hashlib.sha256(
                        "\0".join(members).encode("utf-8")
                    ).hexdigest(),
                    "producer": "runtime.gate_runner",
                    "execution_id": os.urandom(16).hex(),
                    "dependencies": [
                        {"gate": item["gate"], "receipt_sha256": item["receipt_sha256"]}
                        for item in dependencies
                    ],
                    "passed": result.get("valid") is True,
                    "result": result,
                },
                authority_key,
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
    authority_key = _authority_key(root, create=False)
    receipts: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for gate_id, spec in GATES.items():
        dependencies = [
            receipts[item] for item in spec.dependencies if item in receipts
        ]
        path = receipt_dir / f"{gate_id}.json"
        receipt = _load_receipt(path, authority_key)
        expected, members = _input_identity(root, spec, dependencies)
        if receipt is None:
            errors.append(f"{gate_id}: missing or invalid receipt")
        elif receipt.get("input_sha256") != expected:
            errors.append(f"{gate_id}: receipt is stale")
        elif receipt.get("passed") is not True:
            errors.append(f"{gate_id}: gate did not pass")
        elif receipt.get("input_count") != len(members) or not members:
            errors.append(f"{gate_id}: execution denominator is incomplete")
        else:
            receipts[gate_id] = receipt
    return {
        "valid": not errors,
        "gate_count": len(GATES),
        "current_passes": len(receipts),
        "errors": errors,
    }
