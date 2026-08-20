"""Append-only project lifecycle, transfer, promotion, and quarantine adapters.

The module performs only explicit, bounded filesystem operations. Existing files
are never overwritten or deleted; removal from an active location is always a
hash-reconciled move into quarantine.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import re
from typing import Callable, Iterable, Mapping

from .intake import inspect_existing_project
from .event_ledger import append_chained_event
from .project_stream_controls import (
    ScopeEnvelope,
    SwitchEvidence,
    TransferPackage,
    authorize_transfer,
    validate_project_switch,
)
from .scheduler import ResourcePolicy, ResourceScheduler


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _fsync_file(path: Path) -> None:
    # Windows rejects fsync on a read-only CRT descriptor.
    with path.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    """Persist a directory entry where the platform exposes directory handles."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _allowed_source(
    source: Path,
    staging_root: Path,
    expected_sha256: str,
    allowed_suffixes: Iterable[str],
) -> list[str]:
    reasons: list[str] = []
    suffixes = {str(item).casefold() for item in allowed_suffixes}
    if (
        not staging_root.is_dir()
        or not source.is_file()
        or not _inside(source, staging_root)
    ):
        reasons.append("source_outside_owned_staging_root")
    if source.suffix.casefold() not in suffixes:
        reasons.append("source_file_type_not_allowed")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        reasons.append("expected_source_digest_invalid")
    elif source.is_file() and _sha(source) != expected_sha256:
        reasons.append("source_digest_mismatch")
    return reasons


def _write_journal_record(
    transaction: Path, sequence: int, state: str, payload: Mapping[str, object]
) -> Path:
    transaction.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "1.0",
        "sequence": sequence,
        "state": state,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "payload": dict(payload),
        "payload_sha256": _stable(payload),
    }
    path = transaction / f"{sequence:04d}-{state}.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, indent=2, default=str)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(transaction)
    return path


def append_event(ledger: Path, kind: str, payload: Mapping[str, object]) -> Path:
    """Append through the shared chained-ledger authority."""
    bound_payload = dict(payload)
    config = ledger.resolve().parent.parent / "engineering-workspace.toml"
    if ledger.name == "events" and config.is_file():
        bound_payload["workspace_config_sha256"] = _sha(config)
    return append_chained_event(ledger, kind, bound_payload)


def register_existing_project(
    project: Path, ledger: Path, *, project_id: str, max_files: int = 10_000
) -> dict[str, object]:
    if not re.fullmatch(r"prj_[A-Za-z0-9_-]+", project_id):
        raise ValueError("project_id must match ^prj_[A-Za-z0-9_-]+$")
    inventory = inspect_existing_project(project, max_files=max_files)
    slug = project_id.removeprefix("prj_")
    record = {
        "project_id": project_id,
        "name": project.resolve().name,
        "state": "registered",
        "classification": "internal",
        "repositories": [
            {
                "repository_id": f"repo_{slug}",
                "logical_root": ".",
                "role": "application",
            }
        ],
        "owners": list(inventory.get("canonical_owner_candidates", ())),
        "policy_overlay": None,
        "memory_namespace": f"project/{project_id}",
        "cross_project_access": "deny",
        "required_gates": ["constitution", "boundary", "tests", "outcome", "evidence"],
        "commissioning_mode": "existing",
    }
    event = append_event(
        ledger, "project-registered", {"project_record": record, "inventory": inventory}
    )
    return {**record, "inventory": inventory, "event": event.as_posix()}


def record_project_transition(
    ledger: Path, *, project_id: str, action: str, evidence: Iterable[str]
) -> dict[str, object]:
    if action not in {"pause", "resume", "archive"}:
        raise ValueError("unsupported project transition")
    evidence = tuple(sorted(set(map(str, evidence))))
    reasons = []
    if not project_id.strip():
        reasons.append("project_id_missing")
    if not evidence:
        reasons.append("transition_evidence_missing")
    if reasons:
        return {"decision": "rejected", "action": action, "reasons": reasons}
    event = append_event(
        ledger, f"project-{action}", {"project_id": project_id, "evidence": evidence}
    )
    return {
        "decision": "accepted",
        "action": action,
        "project_id": project_id,
        "event": event.as_posix(),
    }


def validate_agent_specification(
    ledger: Path, specification: Mapping[str, object]
) -> dict[str, object]:
    tests = specification.get("required_tests", specification.get("tests"))
    reasons = []
    for field in ("agent_id", "template_id", "project_id"):
        if not str(specification.get(field, "")).strip():
            reasons.append(f"{field}_missing")
    if (
        not isinstance(specification.get("permissions"), (list, tuple))
        or not specification["permissions"]
    ):
        reasons.append("permissions_missing")
    if (
        not isinstance(tests, Mapping)
        or not tests
    ):
        reasons.append("required_tests_missing")
    decision = "rejected" if reasons else "validated_candidate"
    event = append_event(
        ledger,
        "agent-specification-rejected" if reasons else "agent-specification-validated-candidate",
        {
            "specification": dict(specification),
            "reasons": reasons,
            "caller_test_assertions_trusted": False,
            "caller_sandbox_assertion_trusted": False,
        },
    )
    return {
        "operation": "agent.specification.validate_and_record",
        "decision": decision,
        "reasons": reasons,
        "validation_state": "invalid" if reasons else "valid",
        "admission_state": "unadmitted",
        "runtime_state": "stopped",
        "authority_state": "none",
        "created": False,
        "assertions_trusted": False,
        "evidence_state": "unverified_references" if specification.get("evidence") else "none",
        "event": event.as_posix(),
        "fingerprint": _stable(specification),
    }


def switch_project(
    ledger: Path, old: ScopeEnvelope, new: ScopeEnvelope, evidence: SwitchEvidence
) -> dict[str, object]:
    decision = validate_project_switch(old, new, evidence)
    if decision.decision != "allow":
        return {
            "decision": "rejected",
            "reasons": decision.reasons,
            "receipt_hash": decision.receipt_hash,
        }
    event = append_event(
        ledger,
        "project-switch",
        {"old": asdict(old), "new": asdict(new), "evidence": asdict(evidence)},
    )
    return {
        "decision": "active",
        "project_id": new.project_id,
        "event": event.as_posix(),
        "receipt_hash": decision.receipt_hash,
    }


def import_transfer(
    workspace_root: Path,
    source: Path,
    destination: Path,
    package: TransferPackage,
    ledger: Path,
) -> dict[str, object]:
    root = workspace_root.resolve()
    source = source.resolve()
    destination = destination.resolve()
    decision = authorize_transfer(package)
    reasons = list(decision.reasons)
    if (
        not root.is_dir()
        or not source.is_file()
        or not _inside(source, root)
        or not _inside(destination, root)
    ):
        reasons.append("transfer_path_outside_workspace_or_missing")
    if destination.exists():
        reasons.append("destination_collision")
    if reasons:
        return {
            "decision": "rejected",
            "reasons": tuple(sorted(set(reasons))),
            "receipt_hash": decision.receipt_hash,
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if _sha(source) != _sha(destination):
        raise RuntimeError("transfer copy hash mismatch")
    event = append_event(
        ledger,
        "transfer-imported",
        {
            "package": asdict(package),
            "source": source.relative_to(root).as_posix(),
            "destination": destination.relative_to(root).as_posix(),
            "sha256": _sha(destination),
        },
    )
    return {
        "decision": "imported",
        "path": destination.as_posix(),
        "sha256": _sha(destination),
        "event": event.as_posix(),
    }


def quarantine_candidates(
    active_root: Path,
    candidates: Iterable[Path],
    quarantine_root: Path,
    ledger: Path,
    *,
    transaction_root: Path | None = None,
    expected_sha256: Mapping[str, str] | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> dict[str, object]:
    root = active_root.resolve()
    quarantine = quarantine_root.resolve()
    supplied = tuple(path.resolve() for path in candidates)
    paths = tuple(sorted(supplied, key=lambda item: item.as_posix().casefold()))
    reasons = []
    if not root.is_dir() or not supplied:
        reasons.append("active_root_or_candidates_invalid")
    if len(set(supplied)) != len(supplied):
        reasons.append("duplicate_candidate")
    if (
        not _inside(quarantine, root.parent)
        or quarantine == root
        or _inside(quarantine, root)
    ):
        reasons.append("quarantine_must_be_sibling_bounded_tree")
    replay_requested = (
        bool(paths)
        and quarantine.is_dir()
        and all(
            _inside(path, root)
            and path != root
            and not path.exists()
            and (quarantine / path.relative_to(root)).exists()
            for path in paths
        )
    )
    for path in paths:
        if (
            path == root
            or not _inside(path, root)
            or (not path.exists() and not replay_requested)
        ):
            reasons.append(f"invalid_candidate:{path}")
        if any(path != other and _inside(path, other) for other in paths):
            reasons.append(f"overlapping_candidate:{path}")
    inventory: list[dict[str, object]] = []
    if not reasons:
        for path in paths:
            if replay_requested:
                replay_target = quarantine / path.relative_to(root)
                files = (
                    (replay_target,)
                    if replay_target.is_file()
                    else tuple(
                        item
                        for item in sorted(replay_target.rglob("*"))
                        if item.is_file()
                    )
                )
                inventory.extend(
                    {
                        "path": item.relative_to(quarantine).as_posix(),
                        "sha256": _sha(item),
                        "size": item.stat().st_size,
                    }
                    for item in files
                )
            else:
                files = (
                    (path,)
                    if path.is_file()
                    else tuple(
                        item for item in sorted(path.rglob("*")) if item.is_file()
                    )
                )
                inventory.extend(
                    {
                        "path": item.relative_to(root).as_posix(),
                        "sha256": _sha(item),
                        "size": item.stat().st_size,
                    }
                    for item in files
                )
    operation_id = _stable(
        {
            "root": root.as_posix(),
            "quarantine": quarantine.as_posix(),
            "inventory": inventory,
        }
    )
    transactions = (
        transaction_root or (ledger.parent / "transactions" / "quarantine")
    ).resolve()
    if (
        not _inside(transactions, root.parent)
        or transactions == root
        or _inside(transactions, root)
    ):
        reasons.append("transaction_root_must_be_sibling_bounded_tree")
    transaction = transactions / operation_id
    committed = transaction / "0003-committed.json"
    if quarantine.exists():
        if committed.is_file() and all(
            (quarantine / str(item["path"])).is_file()
            and _sha(quarantine / str(item["path"])) == item["sha256"]
            for item in inventory
        ):
            return {
                "decision": "quarantined",
                "count": len(inventory),
                "inventory": inventory,
                "event": None,
                "hard_delete": False,
                "idempotent_replay": True,
            }
        reasons.append("quarantine_destination_exists")
    planned = expected_sha256 or {}
    for item in inventory:
        relative = str(item["path"])
        if relative in planned and planned[relative] != item["sha256"]:
            reasons.append(f"source_digest_mismatch:{relative}")
        if (quarantine / relative).exists():
            reasons.append(f"destination_collision:{relative}")
    if reasons:
        return {
            "decision": "rejected",
            "reasons": tuple(sorted(set(reasons))),
            "hard_delete": False,
        }
    transactions.mkdir(parents=True, exist_ok=True)
    _write_journal_record(
        transaction,
        1,
        "intent",
        {
            "active_root": root.as_posix(),
            "quarantine_root": quarantine.as_posix(),
            "inventory": inventory,
        },
    )
    quarantine.mkdir(parents=True, exist_ok=False)
    moved: list[tuple[Path, Path]] = []
    try:
        for index, path in enumerate(paths, start=1):
            if fault_injector:
                fault_injector(f"before_move_{index}")
            # Revalidate every source immediately before mutation.
            for item in inventory:
                item_path = root / str(item["path"])
                if _inside(item_path, path) and (
                    not item_path.is_file() or _sha(item_path) != item["sha256"]
                ):
                    raise RuntimeError(
                        f"source changed before quarantine commit: {item['path']}"
                    )
            target = quarantine / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
            moved.append((path, target))
        for item in inventory:
            target = quarantine / str(item["path"])
            if not target.is_file() or _sha(target) != item["sha256"]:
                raise RuntimeError("quarantine reconciliation failed")
        _write_journal_record(
            transaction,
            2,
            "moved",
            {"moved": [target.as_posix() for _, target in moved]},
        )
    except BaseException as error:
        rollback_errors = []
        for source, target in reversed(moved):
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
            except OSError as rollback_error:
                rollback_errors.append(str(rollback_error))
        _write_journal_record(
            transaction,
            2,
            "rolled-back",
            {
                "error": f"{type(error).__name__}: {error}",
                "rollback_errors": rollback_errors,
            },
        )
        if rollback_errors:
            raise RuntimeError(
                f"quarantine failed and rollback was incomplete: {rollback_errors}"
            ) from error
        raise
    event = append_event(
        ledger,
        "artifacts-quarantined",
        {
            "active_root": root.as_posix(),
            "quarantine_root": quarantine.as_posix(),
            "inventory": inventory,
            "hard_delete": False,
            "transaction_id": operation_id,
        },
    )
    _write_journal_record(
        transaction,
        3,
        "committed",
        {"event": event.as_posix(), "inventory_sha256": _stable(inventory)},
    )
    return {
        "decision": "quarantined",
        "count": len(inventory),
        "inventory": inventory,
        "event": event.as_posix(),
        "hard_delete": False,
        "transaction_id": operation_id,
    }


def promote_capability(
    candidate: Path,
    shared_root: Path,
    ledger: Path,
    evidence: Mapping[str, object],
    *,
    staging_root: Path | None = None,
    expected_source_sha256: str | None = None,
    allowed_suffixes: Iterable[str] = (".json", ".md", ".py", ".toml", ".yaml", ".yml"),
) -> dict[str, object]:
    candidate = candidate.resolve()
    target_root = shared_root.resolve()
    reasons = []
    owned_staging = staging_root.resolve() if staging_root is not None else None
    if owned_staging is None or expected_source_sha256 is None:
        reasons.append("owned_staging_contract_missing")
    else:
        reasons.extend(
            _allowed_source(
                candidate, owned_staging, expected_source_sha256, allowed_suffixes
            )
        )
    for field in (
        "provenance",
        "license",
        "tests",
        "benchmark",
        "approval_id",
        "version",
    ):
        if not evidence.get(field):
            reasons.append(f"{field}_missing")
    if (
        evidence.get("tests_passed") is not True
        or evidence.get("benchmark_passed") is not True
    ):
        reasons.append("validation_not_passed")
    target = (
        target_root
        / str(evidence.get("capability_id", candidate.stem))
        / str(evidence.get("version", "candidate"))
        / candidate.name
    )
    if target.exists():
        reasons.append("release_collision")
    if reasons:
        return {
            "decision": "rejected",
            "reasons": tuple(sorted(set(reasons))),
            "automatic_activation": False,
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    if _sha(candidate) != expected_source_sha256:
        return {
            "decision": "rejected",
            "reasons": ("source_digest_changed_before_commit",),
            "automatic_activation": False,
        }
    shutil.copy2(candidate, target)
    if _sha(target) != expected_source_sha256:
        raise RuntimeError("capability promotion hash mismatch")
    event = append_event(
        ledger,
        "capability-promoted",
        {
            "target": target.as_posix(),
            "sha256": _sha(target),
            "evidence": dict(evidence),
        },
    )
    return {
        "decision": "released",
        "target": target.as_posix(),
        "sha256": _sha(target),
        "event": event.as_posix(),
        "automatic_activation": False,
    }


def dispatch_workstreams(
    items: Iterable[Mapping[str, object]],
    snapshot: Mapping[str, float | int],
    policy: ResourcePolicy = ResourcePolicy(),
) -> dict[str, object]:
    scheduler = ResourceScheduler(policy)
    assignments = []
    blocked = []
    for item in items:
        work_id = str(item.get("work_id", ""))
        lane = str(item.get("lane", "light"))
        owned_paths = tuple(map(str, item.get("owned_paths", ())))
        worker_id = str(item.get("worker_id", ""))
        admission = scheduler.admit(work_id, lane, snapshot, owned_paths=owned_paths)
        if not admission.admitted:
            blocked.append({"work_id": work_id, "reason": admission.reason})
            continue
        if worker_id:
            scheduler.assign_worker(worker_id, work_id)
        assignments.append(
            {
                "work_id": work_id,
                "worker_id": worker_id,
                "lane": lane,
                "owned_paths": owned_paths,
            }
        )
    return {"assignments": assignments, "blocked": blocked, "bounded": True}


def project_health(metrics: Mapping[str, object]) -> dict[str, object]:
    required = ("tests", "security", "evidence", "dependencies", "memory", "operations")
    scores: dict[str, float] = {}
    unknown = []
    for name in required:
        value = metrics.get(name)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0 <= float(value) <= 1
        ):
            unknown.append(name)
        else:
            scores[name] = round(float(value), 4)
    overall = round(sum(scores.values()) / len(scores), 4) if scores else 0.0
    return {
        "overall": overall,
        "dimensions": scores,
        "unknown": unknown,
        "certifying": not unknown,
    }


def evaluate_resilience(
    experiments: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Evaluate bounded digital-twin experiments; never inject faults into live systems."""
    allowed_faults = {
        "unavailable",
        "latency",
        "corrupt_response",
        "resource_pressure",
        "dependency_failure",
    }
    results = []
    for experiment in experiments:
        reasons = []
        if str(experiment.get("fault", "")) not in allowed_faults:
            reasons.append("fault_not_allowed")
        if experiment.get("digital_twin") is not True:
            reasons.append("not_a_digital_twin")
        if experiment.get("approved") is not True:
            reasons.append("experiment_not_approved")
        if not experiment.get("baseline_evidence") or not experiment.get(
            "observed_evidence"
        ):
            reasons.append("experiment_evidence_incomplete")
        if experiment.get("rollback_verified") is not True:
            reasons.append("rollback_not_verified")
        results.append(
            {
                "experiment_id": str(experiment.get("experiment_id", "unknown")),
                "status": "passed"
                if not reasons and experiment.get("outcome_met") is True
                else "failed",
                "reasons": reasons
                + (
                    [] if experiment.get("outcome_met") is True else ["outcome_not_met"]
                ),
            }
        )
    return {
        "mode": "digital_twin_only",
        "experiments": results,
        "passed": bool(results) and all(item["status"] == "passed" for item in results),
        "live_fault_injection": False,
    }


def guarded_change(
    active_root: Path,
    staged_file: Path,
    destination: Path,
    quarantine_root: Path,
    ledger: Path,
    evidence: Mapping[str, object],
    *,
    staging_root: Path | None = None,
    expected_source_sha256: str | None = None,
    allowed_suffixes: Iterable[str] = (".json", ".md", ".py", ".toml", ".yaml", ".yml"),
    collision_policy: str = "reject",
) -> dict[str, object]:
    root = active_root.resolve()
    staged = staged_file.resolve()
    destination = destination.resolve()
    reasons = []
    if not root.is_dir() or not _inside(destination, root):
        reasons.append("change_paths_invalid")
    owned_staging = staging_root.resolve() if staging_root is not None else None
    if owned_staging is None or expected_source_sha256 is None:
        reasons.append("owned_staging_contract_missing")
    else:
        reasons.extend(
            _allowed_source(
                staged, owned_staging, expected_source_sha256, allowed_suffixes
            )
        )
    if collision_policy not in {"reject"}:
        reasons.append("unsupported_destination_collision_policy")
    if destination.exists() and collision_policy == "reject":
        reasons.append("destination_collision")
    for field in (
        "intent",
        "tests",
        "outcome_contract",
        "rollback",
        "approval_id",
        "idempotency_key",
    ):
        if not evidence.get(field):
            reasons.append(f"{field}_missing")
    if (
        evidence.get("tests_passed") is not True
        or evidence.get("outcome_passed") is not True
    ):
        reasons.append("validation_not_passed")
    if reasons:
        event = append_event(
            ledger,
            "change-rejected",
            {
                "source_sha256": _sha(staged) if staged.is_file() else None,
                "source_mutated": False,
                "reasons": reasons,
                "hard_delete": False,
            },
        )
        return {
            "decision": "rejected",
            "reasons": tuple(sorted(set(reasons))),
            "event": event.as_posix(),
            "source_mutated": False,
            "hard_delete": False,
        }
    if _sha(staged) != expected_source_sha256:
        return {
            "decision": "rejected",
            "reasons": ("source_digest_changed_before_commit",),
            "source_mutated": False,
            "hard_delete": False,
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged, destination)
    if _sha(destination) != expected_source_sha256:
        raise RuntimeError("guarded change hash mismatch")
    event = append_event(
        ledger,
        "change-accepted",
        {
            "destination": destination.relative_to(root).as_posix(),
            "sha256": _sha(destination),
            "evidence": dict(evidence),
        },
    )
    return {
        "decision": "accepted",
        "destination": destination.as_posix(),
        "sha256": _sha(destination),
        "event": event.as_posix(),
    }


def recover_incident(
    active_root: Path,
    recovery_candidate: Path,
    destination: Path,
    quarantine_root: Path,
    ledger: Path,
    evidence: Mapping[str, object],
    *,
    staging_root: Path | None = None,
    transaction_root: Path | None = None,
    expected_source_sha256: str | None = None,
    allowed_suffixes: Iterable[str] = (".json", ".md", ".py", ".toml", ".yaml", ".yml"),
    collision_policy: str = "replace_preserving_previous",
    fault_injector: Callable[[str], None] | None = None,
) -> dict[str, object]:
    root = active_root.resolve()
    candidate = recovery_candidate.resolve()
    destination = destination.resolve()
    quarantine = quarantine_root.resolve()
    reasons = []
    if not root.is_dir() or not _inside(destination, root):
        reasons.append("recovery_paths_invalid")
    owned_staging = staging_root.resolve() if staging_root is not None else None
    if owned_staging is None or expected_source_sha256 is None:
        reasons.append("owned_staging_contract_missing")
    else:
        reasons.extend(
            _allowed_source(
                candidate, owned_staging, expected_source_sha256, allowed_suffixes
            )
        )
    transactions = (
        transaction_root or (ledger.parent / "transactions" / "recovery")
    ).resolve()
    if (
        not _inside(transactions, root.parent)
        or transactions == root
        or _inside(transactions, root)
    ):
        reasons.append("transaction_root_must_be_sibling_bounded_tree")
    if collision_policy != "replace_preserving_previous":
        reasons.append("unsupported_destination_collision_policy")
    for field in (
        "incident_id",
        "root_cause",
        "recovery_tests",
        "rollback_rehearsal",
        "approval_id",
    ):
        if not evidence.get(field):
            reasons.append(f"{field}_missing")
    if (
        evidence.get("recovery_tests_passed") is not True
        or evidence.get("rollback_rehearsed") is not True
    ):
        reasons.append("recovery_validation_not_passed")
    if reasons:
        return {
            "decision": "escalated",
            "reasons": tuple(sorted(set(reasons))),
            "source_mutated": False,
            "hard_delete": False,
        }
    operation_id = _stable(
        {
            "candidate_sha256": expected_source_sha256,
            "destination": destination.relative_to(root).as_posix(),
            "incident_id": evidence.get("incident_id"),
        }
    )
    transaction = transactions / operation_id
    committed = transaction / "0004-committed.json"
    if (
        committed.is_file()
        and destination.is_file()
        and _sha(destination) == expected_source_sha256
    ):
        return {
            "decision": "recovered",
            "destination": destination.as_posix(),
            "preserved_previous": None,
            "event": None,
            "hard_delete": False,
            "idempotent_replay": True,
            "transaction_id": operation_id,
        }
    if transaction.exists():
        rollback_candidates = tuple(sorted(transaction.glob("rollback-*")))
        if not destination.exists() and rollback_candidates:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(rollback_candidates[-1], destination)
            _write_journal_record(
                transaction,
                len(tuple(transaction.glob("*.json"))) + 1,
                "rolled-back-after-interruption",
                {"destination": destination.as_posix()},
            )
        return {
            "decision": "escalated",
            "reasons": ("incomplete_transaction_recovered_original",),
            "source_mutated": False,
            "hard_delete": False,
            "transaction_id": operation_id,
        }
    if destination.exists() and (
        not _inside(quarantine, root.parent) or quarantine.exists()
    ):
        return {
            "decision": "escalated",
            "reasons": ("recovery_quarantine_invalid",),
            "hard_delete": False,
        }
    transactions.mkdir(parents=True, exist_ok=True)
    _write_journal_record(
        transaction,
        1,
        "intent",
        {
            "destination": destination.as_posix(),
            "expected_source_sha256": expected_source_sha256,
            "quarantine_root": quarantine.as_posix(),
            "evidence_sha256": _stable(evidence),
        },
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    prepared = destination.parent / f".{destination.name}.{operation_id[:12]}.prepared"
    preserved = transaction / f"rollback-{destination.name}"
    try:
        if fault_injector:
            fault_injector("before_prepare_copy")
        shutil.copy2(candidate, prepared)
        if (
            _sha(candidate) != expected_source_sha256
            or _sha(prepared) != expected_source_sha256
        ):
            raise RuntimeError("recovery artifact hash mismatch before commit")
        _fsync_file(prepared)
        _write_journal_record(
            transaction,
            2,
            "prepared",
            {"prepared": prepared.as_posix(), "sha256": expected_source_sha256},
        )
        if fault_injector:
            fault_injector("after_prepare")
        if destination.exists():
            os.replace(destination, preserved)
        if fault_injector:
            fault_injector("after_preserve")
        os.replace(prepared, destination)
        _fsync_directory(destination.parent)
        if _sha(destination) != expected_source_sha256:
            raise RuntimeError("recovery destination hash mismatch")
        _write_journal_record(
            transaction,
            3,
            "replaced",
            {"destination": destination.as_posix(), "sha256": expected_source_sha256},
        )
    except BaseException as error:
        abandoned = transaction / f"abandoned-{destination.name}"
        if (
            destination.exists()
            and _sha(destination) == expected_source_sha256
            and preserved.exists()
        ):
            os.replace(destination, abandoned)
        elif prepared.exists():
            os.replace(prepared, abandoned)
        if preserved.exists():
            os.replace(preserved, destination)
            _fsync_directory(destination.parent)
        _write_journal_record(
            transaction,
            len(tuple(transaction.glob("*.json"))) + 1,
            "rolled-back",
            {
                "error": f"{type(error).__name__}: {error}",
                "destination_restored": destination.exists(),
            },
        )
        raise
    if preserved.exists():
        quarantine.mkdir(parents=True, exist_ok=False)
        quarantined_previous = quarantine / destination.relative_to(root)
        quarantined_previous.parent.mkdir(parents=True, exist_ok=True)
        os.replace(preserved, quarantined_previous)
        preserved_result: Path | None = quarantined_previous
    else:
        preserved_result = None
    event = append_event(
        ledger,
        "incident-recovered",
        {
            "destination": destination.relative_to(root).as_posix(),
            "sha256": _sha(destination),
            "preserved_previous": preserved_result.as_posix()
            if preserved_result
            else None,
            "evidence": dict(evidence),
            "hard_delete": False,
            "transaction_id": operation_id,
        },
    )
    _write_journal_record(
        transaction,
        4,
        "committed",
        {"event": event.as_posix(), "destination_sha256": expected_source_sha256},
    )
    return {
        "decision": "recovered",
        "destination": destination.as_posix(),
        "preserved_previous": preserved_result.as_posix() if preserved_result else None,
        "event": event.as_posix(),
        "hard_delete": False,
        "transaction_id": operation_id,
    }
