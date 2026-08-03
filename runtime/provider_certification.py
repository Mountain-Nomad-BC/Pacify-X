"""Executable adversarial certification for optional project-scoped memory providers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from .memory_fabric import MemoryDecision, ProviderIsolationConfig


class BoundMemoryProvider(Protocol):
    def put(self, key: str, value: str, *, created_by: str) -> None: ...
    def get(self, key: str) -> Mapping[str, object] | None: ...
    def search(self, query: str) -> Sequence[Mapping[str, object]]: ...
    def prompt_log(self) -> Sequence[str]: ...
    def correct(self, key: str, value: str, *, created_by: str) -> None: ...
    def inject_failure(self, operation: str) -> None: ...


class ProviderOperationError(RuntimeError):
    """Typed provider failure required by the certification boundary."""

    def __init__(self, operation: str, code: str, message: str) -> None:
        super().__init__(message)
        self.operation = operation
        self.code = code


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    passed: bool
    execution_id: str
    observed_sha256: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderCertificate:
    certificate_id: str
    provider_id: str
    provider_version: str
    project_id: str
    executed_utc: str
    harness_version: str
    config_sha256: str
    tests: tuple[ProbeResult, ...]
    evidence_refs: tuple[str, ...]
    decision: str


def _stable(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _probe(name: str, function: Callable[[], bool]) -> ProbeResult:
    execution_id = _stable({"name": name, "started": datetime.now(timezone.utc).isoformat()})[:24]
    try:
        passed = function() is True
        observed = {"name": name, "passed": passed}
        return ProbeResult(name, passed, execution_id, _stable(observed), None if passed else "AssertionFailed")
    except Exception as error:
        observed = {"name": name, "passed": False, "error": type(error).__name__}
        return ProbeResult(name, False, execution_id, _stable(observed), type(error).__name__)


def run_provider_isolation_suite(
    factory: Callable[[ProviderIsolationConfig], BoundMemoryProvider],
    config: ProviderIsolationConfig,
    *,
    provider_id: str,
    provider_version: str,
    evidence_root: Path | None = None,
) -> tuple[MemoryDecision, ProviderCertificate]:
    if not provider_id or not provider_version:
        raise ValueError("provider identity and version are required")
    if config.shared_process or config.source_of_truth:
        raise ValueError("provider must be isolated and remain an acceleration layer")
    foreign_config = replace(
        config,
        project_id=f"{config.project_id}-foreign",
        root=config.root.parent / f"{config.root.name}-foreign",
        database_namespace=f"{config.database_namespace}-foreign",
        index_namespace=f"{config.index_namespace}-foreign",
        process_namespace=f"{config.process_namespace}-foreign",
    )
    local = factory(config)
    foreign = factory(foreign_config)
    key = "provider-isolation-probe"
    local_value = "local-synthetic-value"
    foreign_value = "foreign-synthetic-value"
    local.put(key, local_value, created_by="agent-local")

    tests = []
    tests.append(_probe("foreign_read_denied", lambda: foreign.get(key) is None))

    def foreign_write_isolated() -> bool:
        foreign.put(key, foreign_value, created_by="agent-foreign")
        return local.get(key) is not None and local.get(key).get("value") == local_value
    tests.append(_probe("foreign_write_denied", foreign_write_isolated))
    tests.append(_probe(
        "foreign_prompt_log_denied",
        lambda: all(local_value not in item for item in foreign.prompt_log())
        and all(foreign_value not in item for item in local.prompt_log()),
    ))
    tests.append(_probe(
        "global_slot_isolated",
        lambda: config.database_namespace != foreign_config.database_namespace
        and config.index_namespace != foreign_config.index_namespace
        and config.process_namespace != foreign_config.process_namespace
        and local is not foreign,
    ))
    tests.append(_probe(
        "attribution_preserved",
        lambda: local.get(key) is not None and local.get(key).get("created_by") == "agent-local",
    ))

    def backend_errors_propagate() -> bool:
        local.inject_failure("search")
        try:
            local.search("synthetic")
        except ProviderOperationError as error:
            return (
                error.operation == "search"
                and error.code == "backend_unavailable"
                and error.__cause__ is not None
            )
        return False
    tests.append(_probe("backend_errors_propagated", backend_errors_propagate))

    def correction_not_retrieved() -> bool:
        local.correct(key, "corrected-synthetic-value", created_by="agent-local")
        return all(item.get("value") != local_value for item in local.search(local_value))
    tests.append(_probe("correction_non_retrieval_proved", correction_not_retrieved))

    config_hash = _stable(asdict(config))
    passed = all(item.passed for item in tests)
    executed = datetime.now(timezone.utc).isoformat()
    certificate_id = _stable({"provider": provider_id, "version": provider_version, "config": config_hash, "tests": [asdict(item) for item in tests]})
    evidence_refs: tuple[str, ...] = ()
    certificate = ProviderCertificate(
        certificate_id, provider_id, provider_version, config.project_id, executed,
        "provider-isolation-harness-v1", config_hash, tuple(tests), evidence_refs,
        "certified_accelerator" if passed else "disabled",
    )
    if evidence_root is not None:
        evidence_root.mkdir(parents=True, exist_ok=True)
        path = evidence_root / f"{certificate_id}.json"
        evidence_refs = (path.as_posix(),)
        certificate = replace(certificate, evidence_refs=evidence_refs)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(asdict(certificate), stream, indent=2)
            stream.write("\n")
    failed = tuple(sorted(item.name for item in tests if not item.passed))
    return MemoryDecision(
        "certified_accelerator" if passed else "disabled",
        tuple(f"isolation_test_failed:{name}" for name in failed),
        config.project_id,
    ), certificate
