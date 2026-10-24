"""Guarded generated-registry publication through native admission and custody.

Builders supply the generated content; this owner never refreshes it, grants
work admission, or treats a projection as canonical evidence.
"""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4
from typing import Mapping


class GuardedProjectionError(ValueError):
    pass


def _note_closure_failure(primary: BaseException, phase: str, error: BaseException) -> None:
    # Failure annotation is diagnostic only. Even hostile exception overrides
    # must never replace the actual publication/settlement failure.
    try:
        BaseException.add_note(primary, phase + " remains uncertain: " +
            type(error).__name__ + ": " + str(error))
    except BaseException:
        pass


def _admit_projection_write(root: Path, admission_event_id: str | None) -> None:
    from .operational_gap_ledger import read_snapshot, guard_work_admission
    if type(admission_event_id) is not str or not admission_event_id:
        raise GuardedProjectionError("publication requires an explicit current work admission")
    snapshot = read_snapshot(root)
    admission = next((row for row in snapshot.get("work_admissions", [])
                      if row.get("event_id") == admission_event_id), None)
    if admission is None:
        raise GuardedProjectionError("publication admission is absent")
    effect_scope = next((row for row in admission.get("effect_scopes", [])
                         if row.get("effect") == "write"), None)
    if effect_scope is None:
        raise GuardedProjectionError("publication has no write admission")
    scope = effect_scope["scope"]
    guard_work_admission(snapshot, gap_id=admission["gap_id"], effect="write",
                         scope=scope, admission_event_id=admission_event_id)
    # Lease/intent ledgers and their locks are effects too; callers must admit
    # their actual custody scope, not merely the destination projection.
    required = ("registry", ".agentic_engineering_os_px/runtime-core",
                ".agentic_engineering_os_px/resource-lifecycle")
    for target in required:
        if not any(target == str(item).rstrip("/") or
                   target.startswith(str(item).rstrip("/") + "/") for item in scope):
            raise GuardedProjectionError("publication write scope omits " + target)


def publish_guarded_registry_projection(
    root: Path, relative: str, image: Mapping, *, admission_event_id: str | None
) -> dict[str, object]:
    from .archive_io import reject_path_links
    from .json_io import bounded_canonical_json_bytes
    reject_path_links(Path(root))
    root = Path(root).resolve(strict=True)
    if (type(relative) is not str or "\\" in relative
            or not relative.startswith("registry/") or not relative.endswith(".json")
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or PurePosixPath(relative).is_absolute()):
        raise GuardedProjectionError("exact project-relative registry JSON target required")
    if not isinstance(image, Mapping):
        raise GuardedProjectionError("generated registry projection must be an object")
    bounded_canonical_json_bytes(dict(image), max_bytes=16 * 1024 * 1024)
    _admit_projection_write(root, admission_event_id)
    return _publish_guarded_json_image(root, relative, image, admission_event_id=admission_event_id,
        scopes=("registry",), recheck=lambda: _admit_projection_write(root, admission_event_id))


def publish_guarded_studio_operation_mirror(root: Path, relative: str, *, admission_event_id: str | None):
    """Only the two exact shipped mirrors may copy the current canonical owner."""
    from .archive_io import reject_path_links
    from .json_io import decode_json_object, read_bounded_bytes
    from .operational_gap_ledger import read_snapshot, guard_work_admission
    if relative not in {"runtime/studio_operations.json", "extension/resources/studio-operations.json"}:
        raise GuardedProjectionError("exact declared Studio operation mirror required")
    reject_path_links(Path(root)); root=Path(root).resolve(strict=True)
    owner=root/"registry/studio_operations.json"; reject_path_links(owner)
    def admitted():
        _admit_projection_write(root,admission_event_id)
        snapshot=read_snapshot(root)
        admission=next(row for row in snapshot["work_admissions"] if row["event_id"]==admission_event_id)
        scope=next(row["scope"] for row in admission["effect_scopes"] if row["effect"]=="write")
        if not any(relative==x.rstrip("/") or relative.startswith(x.rstrip("/")+"/") for x in scope):
            raise GuardedProjectionError("Studio mirror target lacks exact write admission")
        read=next((row for row in admission["effect_scopes"] if row["effect"]=="read"),None)
        if read is None or not any("registry/studio_operations.json"==x.rstrip("/") or "registry/studio_operations.json".startswith(x.rstrip("/")+"/") for x in read["scope"]):
            raise GuardedProjectionError("Studio canonical owner lacks read admission")
        guard_work_admission(snapshot,gap_id=admission["gap_id"],effect="read",scope=read["scope"],admission_event_id=admission_event_id)
    admitted()
    raw=bytes(read_bounded_bytes(owner,max_bytes=65536))
    image=decode_json_object(raw,max_bytes=65536)
    if set(image)!={"schema_version","kinds"} or image["schema_version"]!="px.studio-operation-contract/1.0" or type(image["kinds"]) is not dict:
        raise GuardedProjectionError("exact canonical Studio operation contract required")
    expected=(json.dumps(image,indent=2,sort_keys=True)+"\n").encode()
    if raw!=expected:
        raise GuardedProjectionError("canonical Studio owner must use the native exact serializer")
    def recheck():
        admitted();reject_path_links(owner)
        if bytes(read_bounded_bytes(owner,max_bytes=65536))!=raw:
            raise GuardedProjectionError("canonical Studio owner changed during mirror publication")
    return _publish_guarded_json_image(root,relative,image,admission_event_id=admission_event_id,
        scopes=(relative,),recheck=recheck)


def _publish_guarded_json_image(root,relative,image,*,admission_event_id,scopes,recheck):
    from .archive_io import reject_path_links
    from .scope_lease import ScopeLeaseStore
    from .effect_intent import EffectIntentLedger
    from .studio_models import write_json_atomic
    from .resource_lifecycle import ResourceManager, RunState
    target = root / relative
    reject_path_links(target)
    execution_id = "producer-publication-" + uuid4().hex
    lease_id = "lease-" + execution_id
    intent_key = "intent-" + execution_id
    leases, intents = ScopeLeaseStore(root), EffectIntentLedger(root)
    leases.acquire(lease_id=lease_id, execution_id=execution_id, effect="write",
        scopes=scopes, reason="publish explicitly admitted generated registry projection",
        expires_utc=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
    expected=(json.dumps(image,indent=2,sort_keys=True)+"\n").encode()
    def require_native_owner():
        if any(row["binding"]["lease_id"]==lease_id and row["binding"]["execution_id"]==execution_id for row in leases.quarantines(effect="write")):
            raise GuardedProjectionError("native publication lease has unresolved quarantine")
        if not any(row.lease_id==lease_id and row.execution_id==execution_id and row.scopes==scopes for row in leases.active(effect="write")):
            raise GuardedProjectionError("native publication lease expired or changed")
    intended = False
    published = False
    workspace = None
    manager = None
    primary_error = None
    closure_errors = []
    try:
        recheck()
        require_native_owner()
        manager = ResourceManager(root / ".agentic_engineering_os_px/resource-lifecycle/resources.json",
            receipt_dir=root / ".agentic_engineering_os_px/resource-lifecycle/cleanup-receipts")
        intents.intend(idempotency_key=intent_key, execution_id=execution_id,
                       effect="write", scopes=scopes)
        intended = True
        target.parent.mkdir(parents=True, exist_ok=True)
        workspace_root = root / ".agentic_engineering_os_px/resource-lifecycle/publication-workspaces"
        reject_path_links(workspace_root)
        workspace_root.mkdir(parents=True, exist_ok=True)
        workspace = manager.create_workspace(workspace_root, project_id=str(root),
            run_id=execution_id, lane_id="producer-publication",
            creator="guarded-registry-projection", prefix=".producer-publication-")
        prepared = Path(workspace.path) / "projection.json"
        write_json_atomic(prepared, image)
        recheck()
        reject_path_links(target)
        require_native_owner()
        os.replace(prepared, target)
        published = True
        actual=target.read_bytes()
        if actual!=expected:
            raise GuardedProjectionError("native publication readback differs from exact source image")
        recheck()
        require_native_owner()
        result_sha256 = hashlib.sha256(actual).hexdigest()
        intents.commit(idempotency_key=intent_key, execution_id=execution_id,
                       result_sha256=result_sha256)
    except BaseException as error:
        primary_error = error
        # Once replaced, an uncommitted publication is uncertain, not failed:
        # leave its native in-flight intent for owned recovery/reconciliation.
        if intended and not published:
            try:
                intents.fail(idempotency_key=intent_key, execution_id=execution_id,
                             failure_type=type(error).__name__)
            except BaseException as settlement_error:
                closure_errors.append(("effect intent failure settlement", settlement_error))
        raise
    finally:
        if workspace is not None and manager is not None:
            try:
                cleanup = manager.reclaim_ephemeral_path(workspace.resource_id,
                    reason="producer publication settled",
                    state=RunState.COMPLETED if published else RunState.FAILED)
                if cleanup.resources_failed or cleanup.errors:
                    raise GuardedProjectionError("publication temporary custody did not close")
            except BaseException as cleanup_error:
                closure_errors.append(("temporary custody cleanup", cleanup_error))
        try:
            leases.release(lease_id=lease_id, execution_id=execution_id)
        except BaseException as release_error:
            closure_errors.append(("scope lease release", release_error))
        if closure_errors:
            if primary_error is not None:
                for phase, error in closure_errors:
                    _note_closure_failure(primary_error, phase, error)
            else:
                failure = GuardedProjectionError("publication occurred but native custody closure remains uncertain")
                for phase, error in closure_errors:
                    _note_closure_failure(failure, phase, error)
                raise failure from closure_errors[0][1]
    return {"valid": True, "path": relative,
            "execution_id": execution_id, "effect_intent_key": intent_key,
            "result_sha256": result_sha256}
