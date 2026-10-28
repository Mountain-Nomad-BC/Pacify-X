"""T.I.E. — Tenacious Integrated Experiences: the canonical experience lifecycle.

T.I.E. is accumulated operational experience about a specific, immutable Studio
object (skill, agent, workflow, knowledge source, model). It is not a second
memory universe: this owner is a thin lifecycle layer over the existing
``runtime.usage_memory`` object-local store, which remains the single capture
authority. Nothing here invents records, promotes authority, or copies experience
between objects.

Lifecycle (owner requirement):

    capture -> retrieve -> reconcile -> rebuild context -> reintegrate -> continue

plus the operations the owner plan names explicitly: ``migrate`` (move an
object's experience to its new canonical identity without losing provenance),
``isolate`` (enforce that an object only ever reads its own experience), and
``refine`` (fold a newer outcome into the object's own rollup).

Model output is unverified experience until an admitted native record proves
otherwise: this owner stores outcome metadata only, never prompts or model text.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import os
import json
import hashlib

from .archive_io import reject_path_links, portable_member_name
from .json_io import read_bounded_bytes, decode_json_object
from .effect_intent import EffectIntentLedger
from .scope_lease import ScopeLeaseStore
from .resource_lifecycle import ResourceManager, RunState
from .wal_transaction import _fsync_directory

from .usage_memory import (
    SUBJECT_KINDS,
    fuse_tie_experience,
    rebuild_studio_stats,
    record_studio_observation,
    retrieve_studio_experience,
)

SCHEMA_VERSION = "px.tie-lifecycle/1.0"
RECEIPT_ROOT = Path(".agentic_engineering_os_px/runtime-core/tie-migrations/receipts")
RECEIPT_LIMIT = 4 * 1024 * 1024


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _receipt_target(root, path):
    target = Path(path).absolute()
    if ".." in target.parts:
        raise TieError("migration receipt contains parent traversal")
    try:
        relative = target.relative_to(root / RECEIPT_ROOT)
    except ValueError as error:
        raise TieError("migration receipt requires the canonical PX-owned custody namespace") from error
    if len(relative.parts) != 1 or target.suffix != ".json" or len(target.name.encode("utf-8")) > 256:
        raise TieError("migration receipt requires one bounded canonical JSON filename")
    portable_member_name(target.name, allow_directory=False, max_bytes=256)
    reject_path_links(target)
    return target


def _migration_owner_image(root, kind, identity, version):
    from .studio_models import studio_revision_root, digest
    from .usage_memory import _studio_memory
    memory = _studio_memory(root, kind, identity, version)
    record = studio_revision_root(root, kind, identity) / version / "record.json"
    reject_path_links(record)
    image = bytes(read_bounded_bytes(record, max_bytes=4 * 1024 * 1024))
    payload = decode_json_object(image, max_bytes=4 * 1024 * 1024)
    value = payload.get("record")
    if (not isinstance(value, dict) or value.get(kind + "_id") != identity
            or value.get("version") != version or payload.get("sha256") != digest(value)):
        raise TieError("migration captured immutable owner image is invalid")
    return memory, hashlib.sha256(image).hexdigest()


def _verify_migration_images(root, binding, source, commitments):
    """Prove captured source and actual committed destination rows independently."""
    from .usage_memory import _load_records, _require_record_custody, _validate_observation
    kind, identity, version, new_identity, new_version = binding
    source_memory, source_owner_sha = _migration_owner_image(root, kind, identity, version)
    destination_memory, destination_owner_sha = _migration_owner_image(root, kind, new_identity, new_version)
    source_log = source_memory / "usage.jsonl"
    reject_path_links(source_log)
    raw = bytes(read_bounded_bytes(source_log, max_bytes=16 * 1024 * 1024))
    if hashlib.sha256(raw).hexdigest() != source["experience_log_sha256"]:
        raise TieError("migration captured source image changed; current-source claim refused")
    current = retrieve_studio_experience(root, kind, identity, version, max_records=None)
    if current != source:
        raise TieError("migration source attribution/custody differs from captured image")
    destination_log = destination_memory / "usage.jsonl"
    reject_path_links(destination_log)
    destination_raw = bytes(read_bounded_bytes(destination_log, max_bytes=16 * 1024 * 1024)) if destination_log.is_file() else b""
    records = _load_records(root, kind, new_identity, memory=destination_memory, log_image=destination_raw, strict=True)
    sources = {_sha(row): row for row in source["records"]}
    seen = set()
    for item in commitments:
        source_sha = item["source_record_sha256"]
        if source_sha in seen or source_sha not in sources:
            raise TieError("migration source commitment is duplicated or absent")
        seen.add(source_sha)
        matches = [row for row in records if row.get("tie_effect_key") == item["effect_intent_key"]]
        if len(matches) != 1 or _sha(matches[0]) != item["destination_record_sha256"]:
            raise TieError("migration destination image commitment differs")
        row = matches[0]
        _require_record_custody(root, destination_memory, [row])
        original = sources[source_sha]
        expected = _validate_observation({**{k: v for k, v in original.items() if k not in
            {"schema_version", "subject_id", "subject_kind", "subject_revision", "tie_effect_key", "tie_observation_sha256"}},
            "subject_revision": new_version, "migrated_from": f"{kind}:{identity}@{version}",
            "source_log_sha256": source["experience_log_sha256"], "source_record_sha256": source_sha})
        expected.update(subject_kind=kind, subject_id=new_identity)
        if {k: v for k, v in row.items() if k not in {"tie_effect_key", "tie_observation_sha256"}} != expected:
            raise TieError("migration destination content does not match exact source provenance")
    return {"source_owner_sha256": source_owner_sha, "destination_owner_sha256": destination_owner_sha,
            "destination_log_sha256": hashlib.sha256(destination_raw).hexdigest()}


def _receipt_identity(target, root, binding, source, owner_images):
    return "tie-migration-receipt-" + _sha({"target": target.relative_to(root).as_posix(),
        "binding": binding, "source_log_sha256": source["experience_log_sha256"],
        "source_owner_sha256": owner_images["source_owner_sha256"],
        "destination_owner_sha256": owner_images["destination_owner_sha256"]})


def _validate_receipt_body(root, target, key, binding, source, body):
    kind, identity, version, new_identity, new_version = binding
    total = source["record_count"]
    commitments = body.get("destination_commitments")
    if not isinstance(commitments, list) or not isinstance(body.get("failures"), list):
        raise TieError("migration receipt requires actual commitment/failure inventories")
    count = len(commitments)
    if (body.get("schema_version") != SCHEMA_VERSION
            or body.get("authority_granted") is not False or body.get("source_retained") is not True
            or body.get("source") != f"{kind}:{identity}@{version}"
            or body.get("destination") != f"{kind}:{new_identity}@{new_version}"
            or body.get("source_log_sha256") != source["experience_log_sha256"]
            or body.get("receipt_effect_key") != key or body.get("receipt_path") != target.relative_to(root).as_posix()
            or body.get("records_total") != total or body.get("records_migrated") != count
            or body.get("status") != ("MIGRATED" if count == total else "PARTIAL_MIGRATION")
            or len(body["failures"]) != total - count
            or type(body.get("already_migrated")) is not int or not 0 <= body["already_migrated"] <= count):
        raise TieError("migration receipt status/count/authority differs from actual migration proof")


def _replay_migration_receipt(root, target, key, binding, source, owner_images):
    fence = EffectIntentLedger(root).fence(key)
    if fence["disposition"] != "committed":
        raise TieError("migration receipt effect remains uncertain; native reconciliation required")
    reject_path_links(target)
    image = bytes(read_bounded_bytes(target, max_bytes=RECEIPT_LIMIT))
    value = decode_json_object(image, max_bytes=RECEIPT_LIMIT)
    _validate_receipt_body(root, target, key, binding, source, value)
    execution_id = "tie-receipt-" + key.rsplit("-", 1)[-1]
    if (fence.get("result_sha256") != hashlib.sha256(image).hexdigest()
            or fence.get("execution_id") != execution_id or fence.get("effect") != "write"
            or fence.get("scopes") != [target.relative_to(root).as_posix()]
            or value.get("receipt_effect_key") != key
            or value.get("receipt_path") != target.relative_to(root).as_posix()
            or value.get("source_log_sha256") != source["experience_log_sha256"]
            or any(value.get(k) != owner_images[k] for k in ("source_owner_sha256", "destination_owner_sha256"))):
        raise TieError("migration receipt native identity/image proof differs")
    if any(row.get("execution_id") == execution_id and (row.get("quarantine") or {}).get("state") != "resolved"
           for row in ScopeLeaseStore(root)._load()):
        raise TieError("migration receipt lease closure remains uncertain")
    observed = _verify_migration_images(root, binding, source, value["destination_commitments"])
    return {**value, "already_migrated": len(value["destination_commitments"]),
            "receipt_replayed": True, "retained_receipt_sha256": hashlib.sha256(image).hexdigest(),
            "current_destination_log_sha256": observed["destination_log_sha256"]}


def _publish_migration_receipt(root, target, key, binding, source, body):
    """A receipt effect owns no object-memory write lease and nests no capture."""
    from .usage_memory import _note_failure
    _validate_receipt_body(root, target, key, binding, source, body)
    scopes = [target.relative_to(root).as_posix()]
    execution_id = "tie-receipt-" + key.rsplit("-", 1)[-1]
    intents = EffectIntentLedger(root)
    leases = ScopeLeaseStore(root)
    lease_id = "tie-receipt-lease-" + uuid4().hex
    leases.acquire(lease_id=lease_id, execution_id=execution_id, effect="write", scopes=scopes,
        reason="native T.I.E. migration receipt custody",
        expires_utc=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
    primary = None
    intended = False
    published = False
    publication_attempted = False
    manager = workspace = None
    def verify_live():
        if any(row.get("lease_id") == lease_id and row.get("quarantine")
               for row in leases._load()):
            raise TieError("migration receipt lease is quarantined; publication refused")
        if not any(row.lease_id == lease_id and row.execution_id == execution_id
                   and tuple(row.scopes) == tuple(scopes) for row in leases.active(effect="write")):
            raise TieError("migration receipt lease is no longer live")
        row = intents.fence(key)
        if row["disposition"] != "in_flight" or row.get("execution_id") != execution_id or row.get("scopes") != scopes:
            raise TieError("migration receipt intent ownership differs")
    def verify_inputs():
        observed = _verify_migration_images(root, binding, source, body["destination_commitments"])
        if any(body[k] != observed[k] for k in observed):
            raise TieError("migration owner/destination source image drifted before settlement")
    try:
        if intents.fence(key)["disposition"] != "new" or target.exists():
            raise TieError("migration receipt collision/uncertainty; overwrite refused")
        intents.intend(idempotency_key=key, execution_id=execution_id, effect="write", scopes=scopes)
        intended = True
        verify_live()
        verify_inputs()
        image = _canonical(body) + b"\n"
        if len(image) > RECEIPT_LIMIT:
            raise TieError("migration receipt exceeds native byte budget")
        manager = ResourceManager(root / ".agentic_engineering_os_px/resource-lifecycle/resources.json",
            receipt_dir=root / ".agentic_engineering_os_px/resource-lifecycle/cleanup-receipts")
        staging_root = root / ".agentic_engineering_os_px/resource-lifecycle/tie-receipt-workspaces"
        reject_path_links(staging_root)
        staging_root.mkdir(parents=True, exist_ok=True)
        workspace = manager.create_workspace(staging_root, project_id=str(root), run_id=execution_id,
            lane_id="tie-migration-receipt", creator="runtime.tie_experience", prefix=".tie-receipt-")
        prepared = Path(workspace.path) / "receipt.json"
        with prepared.open("xb") as stream:
            stream.write(image)
            stream.flush()
            os.fsync(stream.fileno())
        if bytes(read_bounded_bytes(prepared, max_bytes=RECEIPT_LIMIT)) != image:
            raise TieError("migration prepared receipt image differs")
        verify_live()
        verify_inputs()
        reject_path_links(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Hard-link publication is exclusive: no existing owner image is replaced.
        publication_attempted = True
        os.link(prepared, target)
        published = True
        _fsync_directory(target.parent)
        if bytes(read_bounded_bytes(target, max_bytes=RECEIPT_LIMIT)) != image:
            raise TieError("migration retained receipt image differs")
        cleanup = manager.reclaim_ephemeral_path(workspace.resource_id,
            reason="T.I.E. migration receipt image published", state=RunState.COMPLETED)
        if cleanup.resources_failed or cleanup.errors:
            raise TieError("migration receipt staging custody did not close")
        workspace = None
        verify_live()
        verify_inputs()
        intents.commit(idempotency_key=key, execution_id=execution_id,
            result_sha256=hashlib.sha256(image).hexdigest())
        return {**body, "receipt_replayed": False,
                "retained_receipt_sha256": hashlib.sha256(image).hexdigest()}
    except BaseException as error:
        primary = error
        if intended and not publication_attempted:
            try:
                intents.fail(idempotency_key=key, execution_id=execution_id, failure_type=type(error).__name__)
            except BaseException as secondary:
                _note_failure(error, "T.I.E. receipt intent settlement", secondary)
        raise
    finally:
        secondary_errors = []
        if workspace is not None and manager is not None:
            try:
                cleanup = manager.reclaim_ephemeral_path(workspace.resource_id,
                    reason="T.I.E. receipt attempt settled", state=RunState.COMPLETED if published else RunState.FAILED)
                if cleanup.resources_failed or cleanup.errors:
                    raise TieError("migration receipt staging cleanup remains uncertain")
            except BaseException as secondary:
                secondary_errors.append(("receipt staging cleanup", secondary))
        try:
            if not leases.release(lease_id=lease_id, execution_id=execution_id):
                raise TieError("migration receipt lease closure is missing")
        except BaseException as secondary:
            secondary_errors.append(("receipt lease release", secondary))
        if secondary_errors:
            if primary is None:
                primary = TieError("migration receipt native closure remains uncertain")
                for phase, secondary in secondary_errors: _note_failure(primary, phase, secondary)
                raise primary from secondary_errors[0][1]
            for phase, secondary in secondary_errors: _note_failure(primary, phase, secondary)

#: Object kinds that carry T.I.E. experience, mapped onto the canonical
#: ``usage_memory`` subject kinds. A kind absent here has no admitted experience
#: surface and is refused rather than silently bucketed.
TIE_KINDS = {
    "skill": "skill",
    "agent": "agent",
    "workflow": "workflow",
    "knowledge": "knowledge",
    "model": "model",
}


class TieError(ValueError):
    """Raised when a T.I.E. lifecycle request is invalid."""


def _kind(value: str) -> str:
    if value not in TIE_KINDS:
        raise TieError(f"unknown T.I.E. object kind: {value!r}")
    return TIE_KINDS[value]


def capture(root: Path, kind: str, identity: str, version: str, *,
            run_id: str, outcome: str, evidence_ref: str,
            tags: tuple[str, ...] = ()) -> dict[str, Any]:
    """Capture one bounded outcome for an object's own experience store.

    ``outcome`` is metadata (success/failure/partial), never model text. Capture
    failure is reported, never raised into a caller that already completed real
    work, and never silently treated as success.
    """
    _kind(kind)
    if outcome not in {"success", "failure", "partial"}:
        raise TieError("T.I.E. outcome must be success, failure or partial")
    try:
        result = record_studio_observation(root, kind, identity, version, {
            "run_id": run_id, "outcome": outcome, "evidence_ref": evidence_ref,
            "tags": ["tie", *tags],
        })
        return {"schema_version": SCHEMA_VERSION, "status": "CAPTURED", "recorded": True,
                "stats_sha256": result["stats"]["stats_sha256"], "authority_granted": False}
    except Exception as error:  # noqa: BLE001 - capture failure must not fail the work
        return {"schema_version": SCHEMA_VERSION, "status": "CAPTURE_FAILED", "recorded": False,
                "failure_type": type(error).__name__, "reason": str(error)[:512],
                "authority_granted": False}


def retrieve(root: Path, kind: str, identity: str, version: str) -> dict[str, Any]:
    """Read an object's own attributed experience. Corruption is surfaced, not hidden."""
    _kind(kind)
    return retrieve_studio_experience(root, kind, identity, version)


def reconcile(root: Path, kind: str, identity: str, version: str) -> dict[str, Any]:
    """Rebuild the object's derived rollup from its append-only log.

    The rollup is derived and never canonical, so reconciliation can never change
    the recorded outcomes; it only re-derives the summary from the same log image.
    """
    _kind(kind)
    stats = rebuild_studio_stats(root, kind, identity, version)
    return {"schema_version": SCHEMA_VERSION, "status": "RECONCILED",
            "stats_sha256": stats.get("stats_sha256"), "authority_granted": False}


def rebuild_context(root: Path, bindings, *, max_records_per_subject: int = 20) -> dict[str, Any]:
    """Rebuild bounded model context from exact object bindings.

    Delegates to the canonical fusion owner so the same honest
    corrupt/unavailable reporting is used before any context is materialized.
    """
    return fuse_tie_experience(root, bindings, max_records_per_subject=max_records_per_subject)


def migrate(root: Path, kind: str, identity: str, version: str, *,
            new_identity: str, new_version: str, receipt_path: Path) -> dict[str, Any]:
    """Reintegrate an object's experience under its new canonical identity.

    Migration is a *copy* of the append-only log image to the new identity's own
    store, bound by the source log digest, so provenance is preserved and the
    source is left intact. Exact source-record digests make repeated migration
    idempotent; partial migration is reported as partial.
    """
    _kind(kind)
    reject_path_links(Path(root)); root = Path(root).resolve(strict=True)
    target = _receipt_target(root, receipt_path)
    if new_identity == identity and new_version == version:
        raise TieError("migration requires a changed canonical identity or version")
    source = retrieve_studio_experience(root, kind, identity, version, max_records=None)
    if source["record_count"] == 0:
        raise TieError("no source experience to migrate")
    retrieve_studio_experience(root, kind, new_identity, new_version)
    if new_identity == identity:
        return {"schema_version": SCHEMA_VERSION, "status": "REINTEGRATED_SAME_OBJECT",
                "source": f"{kind}:{identity}@{version}",
                "destination": f"{kind}:{new_identity}@{new_version}",
                "source_log_sha256": source["experience_log_sha256"],
                "records_total": source["record_count"], "records_appended": 0,
                "source_retained": True, "authority_granted": False}
    binding = (kind, identity, version, new_identity, new_version)
    owner_images = _verify_migration_images(root, binding, source, [])
    key = _receipt_identity(target, root, binding, source, owner_images)
    fence = EffectIntentLedger(root).fence(key)
    if fence["disposition"] == "committed":
        return _replay_migration_receipt(root, target, key, binding, source, owner_images)
    if fence["disposition"] != "new":
        raise TieError("migration receipt effect remains uncertain; blind retry refused")
    if target.exists():
        raise TieError("migration receipt collision; historical/unfenced image will not be overwritten or adopted")
    commitments = []
    duplicates = 0
    failures = []
    for index, record in enumerate(source["records"]):
        # A detected hard source dependency failure stops before another copy.
        _verify_migration_images(root, binding, source, commitments)
        try:
            source_record_sha256 = _sha(record)
            result = record_studio_observation(root, kind, new_identity, new_version, {
                **{k: v for k, v in record.items() if k not in
                   {"schema_version", "subject_id", "subject_kind", "subject_revision",
                    "tie_effect_key", "tie_observation_sha256"}},
                "migrated_from": f"{kind}:{identity}@{version}",
                "source_log_sha256": source["experience_log_sha256"],
                "source_record_sha256": source_record_sha256,
            })
            destination = result["recorded"]
            if not destination.get("tie_effect_key"):
                raise TieError("historical destination observation has no native commitment; backfill refused")
            candidate = {"source_record_sha256": source_record_sha256,
                "destination_record_sha256": _sha(destination), "effect_intent_key": destination["tie_effect_key"]}
            _verify_migration_images(root, binding, source, [*commitments, candidate])
            commitments.append(candidate)
            duplicates += int(result.get("duplicate") is True)
        except Exception as error:
            failures.append({"record_index": index, "failure_type": type(error).__name__, "reason": str(error)[:512]})
    observed = _verify_migration_images(root, binding, source, commitments)
    if any(observed[k] != owner_images[k] for k in ("source_owner_sha256", "destination_owner_sha256")):
        raise TieError("migration immutable owner image changed; receipt refused")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "MIGRATED" if len(commitments) == source["record_count"] else "PARTIAL_MIGRATION",
        "source": f"{kind}:{identity}@{version}",
        "destination": f"{kind}:{new_identity}@{new_version}",
        "source_log_sha256": source["experience_log_sha256"],
        **observed,
        "destination_commitments": commitments,
        "records_migrated": len(commitments), "records_total": source["record_count"],
        "already_migrated": duplicates, "failures": failures,
        "source_retained": True, "authority_granted": False,
        "receipt_effect_key": key, "receipt_path": target.relative_to(root).as_posix(),
    }
    return _publish_migration_receipt(root, target, key, binding, source, receipt)


def isolate(root: Path, kind: str, identity: str, version: str) -> dict[str, Any]:
    """Prove an object reads only its own experience.

    A record attributed to another object is a violation; the canonical reader
    already refuses such a record, so this surfaces the isolation result rather
    than performing a second scan.
    """
    _kind(kind)
    try:
        result = retrieve_studio_experience(root, kind, identity, version)
        return {"schema_version": SCHEMA_VERSION, "status": "ISOLATED",
                "record_count": result["record_count"], "violations": [],
                "authority_granted": False}
    except (ValueError, OSError) as error:
        return {"schema_version": SCHEMA_VERSION, "status": "ISOLATION_VIOLATION",
                "violations": [str(error)[:512]], "authority_granted": False}


def refine(root: Path, kind: str, identity: str, version: str, *,
           run_id: str, outcome: str, evidence_ref: str) -> dict[str, Any]:
    """Fold a newer outcome into the object's own rollup.

    Refinement never promotes experience to authority and never edits a past
    record: it appends and re-derives, exactly like capture.
    """
    _kind(kind)
    captured = capture(root, kind, identity, version, run_id=run_id, outcome=outcome,
                       evidence_ref=evidence_ref, tags=("refinement",))
    if captured.get("recorded") is not True:
        return captured
    stats = rebuild_studio_stats(root, kind, identity, version)
    return {"schema_version": SCHEMA_VERSION, "status": "REFINED",
            "stats_sha256": stats.get("stats_sha256"), "authority_granted": False}
