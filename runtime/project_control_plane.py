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
from pathlib import Path
import shutil
import re
from typing import Iterable, Mapping

from .intake import inspect_existing_project
from .file_lock import FileLock
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
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def append_event(ledger: Path, kind: str, payload: Mapping[str, object]) -> Path:
    """Append a uniquely named event; no current-state file is overwritten."""
    if not kind or not all(character.isalnum() or character in "-_" for character in kind):
        raise ValueError("event kind must be a bounded identifier")
    ledger.mkdir(parents=True, exist_ok=True)
    with FileLock(ledger / ".event-ledger.lock"):
        sequence = len(tuple(ledger.glob("*.json"))) + 1
        record = {
            "schema_version": "1.0",
            "sequence": sequence,
            "kind": kind,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "payload": dict(payload),
            "payload_sha256": _stable(payload),
        }
        path = ledger / f"{sequence:08d}-{kind}-{record['payload_sha256'][:12]}.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, indent=2, default=str)
            stream.write("\n")
        return path


def register_existing_project(project: Path, ledger: Path, *, project_id: str, max_files: int = 10_000) -> dict[str, object]:
    if not re.fullmatch(r"prj_[A-Za-z0-9_-]+", project_id):
        raise ValueError("project_id must match ^prj_[A-Za-z0-9_-]+$")
    inventory = inspect_existing_project(project, max_files=max_files)
    slug = project_id.removeprefix("prj_")
    record = {
        "project_id": project_id, "name": project.resolve().name, "state": "registered",
        "classification": "internal",
        "repositories": [{"repository_id": f"repo_{slug}", "logical_root": ".", "role": "application"}],
        "owners": list(inventory.get("canonical_owner_candidates", ())), "policy_overlay": None,
        "memory_namespace": f"project/{project_id}", "cross_project_access": "deny",
        "required_gates": ["constitution", "boundary", "tests", "outcome", "evidence"],
        "commissioning_mode": "existing",
    }
    event = append_event(ledger, "project-registered", {"project_record": record, "inventory": inventory})
    return {**record, "inventory": inventory, "event": event.as_posix()}


def record_project_transition(ledger: Path, *, project_id: str, action: str, evidence: Iterable[str]) -> dict[str, object]:
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
    event = append_event(ledger, f"project-{action}", {"project_id": project_id, "evidence": evidence})
    return {"decision": "accepted", "action": action, "project_id": project_id, "event": event.as_posix()}


def register_agent(ledger: Path, specification: Mapping[str, object]) -> dict[str, object]:
    tests = specification.get("tests")
    reasons = []
    for field in ("agent_id", "template_id", "project_id"):
        if not str(specification.get(field, "")).strip():
            reasons.append(f"{field}_missing")
    if not isinstance(specification.get("permissions"), (list, tuple)) or not specification["permissions"]:
        reasons.append("permissions_missing")
    if not isinstance(tests, Mapping) or not tests or not all(value is True for value in tests.values()):
        reasons.append("agent_tests_not_passed")
    if specification.get("sandbox_validated") is not True:
        reasons.append("sandbox_not_validated")
    if not specification.get("evidence"):
        reasons.append("agent_evidence_missing")
    decision = "rejected" if reasons else "active"
    event = append_event(ledger, f"agent-{decision}", {"specification": dict(specification), "reasons": reasons})
    return {"decision": decision, "reasons": reasons, "event": event.as_posix(), "fingerprint": _stable(specification)}


def switch_project(ledger: Path, old: ScopeEnvelope, new: ScopeEnvelope, evidence: SwitchEvidence) -> dict[str, object]:
    decision = validate_project_switch(old, new, evidence)
    if decision.decision != "allow":
        return {"decision": "rejected", "reasons": decision.reasons, "receipt_hash": decision.receipt_hash}
    event = append_event(ledger, "project-switch", {"old": asdict(old), "new": asdict(new), "evidence": asdict(evidence)})
    return {"decision": "active", "project_id": new.project_id, "event": event.as_posix(), "receipt_hash": decision.receipt_hash}


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
    if not root.is_dir() or not source.is_file() or not _inside(source, root) or not _inside(destination, root):
        reasons.append("transfer_path_outside_workspace_or_missing")
    if destination.exists():
        reasons.append("destination_collision")
    if reasons:
        return {"decision": "rejected", "reasons": tuple(sorted(set(reasons))), "receipt_hash": decision.receipt_hash}
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if _sha(source) != _sha(destination):
        raise RuntimeError("transfer copy hash mismatch")
    event = append_event(ledger, "transfer-imported", {
        "package": asdict(package), "source": source.relative_to(root).as_posix(),
        "destination": destination.relative_to(root).as_posix(), "sha256": _sha(destination),
    })
    return {"decision": "imported", "path": destination.as_posix(), "sha256": _sha(destination), "event": event.as_posix()}


def quarantine_candidates(
    active_root: Path,
    candidates: Iterable[Path],
    quarantine_root: Path,
    ledger: Path,
) -> dict[str, object]:
    root = active_root.resolve()
    quarantine = quarantine_root.resolve()
    paths = tuple(sorted({path.resolve() for path in candidates}, key=lambda item: item.as_posix().casefold()))
    reasons = []
    if not root.is_dir() or not paths:
        reasons.append("active_root_or_candidates_invalid")
    if not _inside(quarantine, root.parent) or quarantine == root or _inside(quarantine, root):
        reasons.append("quarantine_must_be_sibling_bounded_tree")
    for path in paths:
        if path == root or not _inside(path, root) or not path.exists():
            reasons.append(f"invalid_candidate:{path}")
        if any(path != other and _inside(path, other) for other in paths):
            reasons.append(f"overlapping_candidate:{path}")
    if quarantine.exists():
        reasons.append("quarantine_destination_exists")
    if reasons:
        return {"decision": "rejected", "reasons": tuple(sorted(set(reasons))), "hard_delete": False}
    inventory: list[dict[str, object]] = []
    for path in paths:
        files = (path,) if path.is_file() else tuple(item for item in sorted(path.rglob("*")) if item.is_file())
        inventory.extend({"path": item.relative_to(root).as_posix(), "sha256": _sha(item), "size": item.stat().st_size} for item in files)
    quarantine.mkdir(parents=True, exist_ok=False)
    for path in paths:
        target = quarantine / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    for item in inventory:
        target = quarantine / str(item["path"])
        if not target.is_file() or _sha(target) != item["sha256"]:
            raise RuntimeError("quarantine reconciliation failed")
    event = append_event(ledger, "artifacts-quarantined", {
        "active_root": root.as_posix(), "quarantine_root": quarantine.as_posix(),
        "inventory": inventory, "hard_delete": False,
    })
    return {"decision": "quarantined", "count": len(inventory), "inventory": inventory, "event": event.as_posix(), "hard_delete": False}


def promote_capability(candidate: Path, shared_root: Path, ledger: Path, evidence: Mapping[str, object]) -> dict[str, object]:
    candidate = candidate.resolve()
    target_root = shared_root.resolve()
    reasons = []
    if not candidate.is_file():
        reasons.append("candidate_missing")
    for field in ("provenance", "license", "tests", "benchmark", "approval_id", "version"):
        if not evidence.get(field):
            reasons.append(f"{field}_missing")
    if evidence.get("tests_passed") is not True or evidence.get("benchmark_passed") is not True:
        reasons.append("validation_not_passed")
    target = target_root / str(evidence.get("capability_id", candidate.stem)) / str(evidence.get("version", "candidate")) / candidate.name
    if target.exists():
        reasons.append("release_collision")
    if reasons:
        return {"decision": "rejected", "reasons": tuple(sorted(set(reasons))), "automatic_activation": False}
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, target)
    if _sha(candidate) != _sha(target):
        raise RuntimeError("capability promotion hash mismatch")
    event = append_event(ledger, "capability-promoted", {"target": target.as_posix(), "sha256": _sha(target), "evidence": dict(evidence)})
    return {"decision": "released", "target": target.as_posix(), "sha256": _sha(target), "event": event.as_posix(), "automatic_activation": False}


def dispatch_workstreams(items: Iterable[Mapping[str, object]], snapshot: Mapping[str, float | int], policy: ResourcePolicy = ResourcePolicy()) -> dict[str, object]:
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
        assignments.append({"work_id": work_id, "worker_id": worker_id, "lane": lane, "owned_paths": owned_paths})
    return {"assignments": assignments, "blocked": blocked, "bounded": True}


def project_health(metrics: Mapping[str, object]) -> dict[str, object]:
    required = ("tests", "security", "evidence", "dependencies", "memory", "operations")
    scores: dict[str, float] = {}
    unknown = []
    for name in required:
        value = metrics.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= float(value) <= 1:
            unknown.append(name)
        else:
            scores[name] = round(float(value), 4)
    overall = round(sum(scores.values()) / len(scores), 4) if scores else 0.0
    return {"overall": overall, "dimensions": scores, "unknown": unknown, "certifying": not unknown}


def evaluate_resilience(experiments: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Evaluate bounded digital-twin experiments; never inject faults into live systems."""
    allowed_faults = {"unavailable", "latency", "corrupt_response", "resource_pressure", "dependency_failure"}
    results = []
    for experiment in experiments:
        reasons = []
        if str(experiment.get("fault", "")) not in allowed_faults:
            reasons.append("fault_not_allowed")
        if experiment.get("digital_twin") is not True:
            reasons.append("not_a_digital_twin")
        if experiment.get("approved") is not True:
            reasons.append("experiment_not_approved")
        if not experiment.get("baseline_evidence") or not experiment.get("observed_evidence"):
            reasons.append("experiment_evidence_incomplete")
        if experiment.get("rollback_verified") is not True:
            reasons.append("rollback_not_verified")
        results.append({
            "experiment_id": str(experiment.get("experiment_id", "unknown")),
            "status": "passed" if not reasons and experiment.get("outcome_met") is True else "failed",
            "reasons": reasons + ([] if experiment.get("outcome_met") is True else ["outcome_not_met"]),
        })
    return {
        "mode": "digital_twin_only", "experiments": results,
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
) -> dict[str, object]:
    root = active_root.resolve()
    staged = staged_file.resolve()
    destination = destination.resolve()
    quarantine = quarantine_root.resolve()
    reasons = []
    if not root.is_dir() or not staged.is_file() or not _inside(destination, root):
        reasons.append("change_paths_invalid")
    if destination.exists():
        reasons.append("destination_collision")
    for field in ("intent", "tests", "outcome_contract", "rollback", "approval_id", "idempotency_key"):
        if not evidence.get(field):
            reasons.append(f"{field}_missing")
    if evidence.get("tests_passed") is not True or evidence.get("outcome_passed") is not True:
        reasons.append("validation_not_passed")
    if reasons:
        if staged.is_file() and _inside(quarantine, root.parent) and not quarantine.exists():
            quarantine.mkdir(parents=True, exist_ok=False)
            quarantined = quarantine / staged.name
            shutil.move(str(staged), str(quarantined))
            event = append_event(ledger, "change-quarantined", {
                "path": quarantined.as_posix(), "sha256": _sha(quarantined), "reasons": reasons,
                "hard_delete": False,
            })
            return {"decision": "quarantined", "reasons": tuple(sorted(set(reasons))), "event": event.as_posix(), "hard_delete": False}
        return {"decision": "rejected", "reasons": tuple(sorted(set(reasons))), "hard_delete": False}
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged, destination)
    if _sha(staged) != _sha(destination):
        raise RuntimeError("guarded change hash mismatch")
    event = append_event(ledger, "change-accepted", {
        "destination": destination.relative_to(root).as_posix(), "sha256": _sha(destination), "evidence": dict(evidence),
    })
    return {"decision": "accepted", "destination": destination.as_posix(), "sha256": _sha(destination), "event": event.as_posix()}


def recover_incident(
    active_root: Path,
    recovery_candidate: Path,
    destination: Path,
    quarantine_root: Path,
    ledger: Path,
    evidence: Mapping[str, object],
) -> dict[str, object]:
    root = active_root.resolve()
    candidate = recovery_candidate.resolve()
    destination = destination.resolve()
    quarantine = quarantine_root.resolve()
    reasons = []
    if not root.is_dir() or not candidate.is_file() or not _inside(destination, root):
        reasons.append("recovery_paths_invalid")
    for field in ("incident_id", "root_cause", "recovery_tests", "rollback_rehearsal", "approval_id"):
        if not evidence.get(field):
            reasons.append(f"{field}_missing")
    if evidence.get("recovery_tests_passed") is not True or evidence.get("rollback_rehearsed") is not True:
        reasons.append("recovery_validation_not_passed")
    if reasons:
        return {"decision": "escalated", "reasons": tuple(sorted(set(reasons))), "hard_delete": False}
    preserved = None
    if destination.exists():
        if not _inside(quarantine, root.parent) or quarantine.exists():
            return {"decision": "escalated", "reasons": ("recovery_quarantine_invalid",), "hard_delete": False}
        quarantine.mkdir(parents=True, exist_ok=False)
        preserved = quarantine / destination.relative_to(root)
        preserved.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(preserved))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, destination)
    if _sha(candidate) != _sha(destination):
        raise RuntimeError("recovery artifact hash mismatch")
    event = append_event(ledger, "incident-recovered", {
        "destination": destination.relative_to(root).as_posix(), "sha256": _sha(destination),
        "preserved_previous": preserved.as_posix() if preserved else None, "evidence": dict(evidence), "hard_delete": False,
    })
    return {"decision": "recovered", "destination": destination.as_posix(), "preserved_previous": preserved.as_posix() if preserved else None, "event": event.as_posix(), "hard_delete": False}
