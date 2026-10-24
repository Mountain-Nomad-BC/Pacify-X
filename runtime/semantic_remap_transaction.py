"""Preserved-copy remap transactions with native admission and rollback custody.

No Git, builds or installs. Apply records APPLIED_PENDING_VERIFICATION; a
completed filesystem transaction does not claim the W2 fixed-point exit gate.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .archive_io import reject_path_links
from .file_lock import FileLock
from .json_io import bounded_canonical_json_bytes, load_json_object, read_bounded_bytes
from .operational_gap_ledger import read_snapshot, guard_work_admission
from .resource_lifecycle import ResourceManager, ResourceClassification
from .semantic_locator import LocatorRegistry
from .semantic_migration import _hash, _path, MAX_FILE_BYTES, MAX_PLAN_BYTES
from .trusted_evidence import TrustedEvidenceResolver, EvidenceScope


def _image_sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _scope_contains(scopes, path):
    return any(path == scope or path.startswith(scope.rstrip("/") + "/") for scope in scopes)


def _authorize(root, *, compilation_sha256, project_id, actor_id, session_id,
               resolver, approval_reference, accepted_producers, gap_id, admission_event_id, write_scopes):
    if type(resolver) is not TrustedEvidenceResolver:
        raise TypeError("remap requires native signed evidence resolution")
    scopes = tuple(write_scopes)
    guard_work_admission(read_snapshot(root), gap_id=gap_id, effect="write", scope=scopes,
                         admission_event_id=admission_event_id)
    approval = resolver.resolve(approval_reference, scope=EvidenceScope(
        project_id, "semantic-remap:" + compilation_sha256, actor_id=actor_id, session_id=session_id),
        accepted_producers=accepted_producers, required_type="human_approval", max_age_seconds=300)
    if not approval.verified or approval.record["result"].get("accepted") is not True:
        raise ValueError("exact current remap compilation is not approved")
    return scopes, approval.record["content_sha256"]


def _write_new(path, raw):
    reject_path_links(path)
    with path.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def _replace_from_stage(target, raw, directory):
    reject_path_links(target)
    stage = directory / ("stage-" + _image_sha(target.as_posix().encode()) + "-" + _image_sha(raw))
    _write_new(stage, raw)
    target.parent.mkdir(parents=True, exist_ok=True)
    reject_path_links(target)
    os.replace(stage, target)


def _receipt(directory, body):
    body = {**body, "receipt_sha256": _hash(body)}
    image = bounded_canonical_json_bytes(body, max_bytes=MAX_PLAN_BYTES)
    _write_new(directory / (body["status"] + ".json"), image)
    return body


def apply_remap(root, proposal, compilation, locators, *, project_id, actor_id, session_id,
                resolver, approval_reference, accepted_producers, gap_id, admission_event_id, write_scopes):
    reject_path_links(Path(root)); root = Path(root).resolve(strict=True)
    if type(locators) is not LocatorRegistry:
        raise TypeError("native locator owner required")
    for record, digest_key in ((proposal, "proposal_sha256"), (compilation, "compilation_sha256")):
        if record.get(digest_key) != _hash({k: v for k, v in record.items() if k != digest_key}) or record.get("authority_granted") is not False:
            raise ValueError("intact proposal and compiled transaction required")
    if compilation["proposal_sha256"] != proposal["proposal_sha256"] or compilation.get("unresolved") or compilation.get("mechanically_ready") is not True:
        raise ValueError("all high-risk references must be mechanically resolved before apply")
    if (proposal["entity_snapshot_sha256"] != locators.entity_snapshot_sha256
            or proposal["locator_snapshot_sha256"] != hashlib.sha256(locators.snapshot_bytes()).hexdigest()):
        raise ValueError("accepted canonical entity/locator ownership changed before apply")
    scopes, approval_sha = _authorize(root, compilation_sha256=compilation["compilation_sha256"],
        project_id=project_id, actor_id=actor_id, session_id=session_id, resolver=resolver,
        approval_reference=approval_reference, accepted_producers=accepted_producers, gap_id=gap_id,
        admission_event_id=admission_event_id, write_scopes=write_scopes)
    source_manifest = compilation["source_manifest"]
    if compilation["source_manifest_sha256"] != _hash(source_manifest):
        raise ValueError("compiled source manifest differs")
    manifest = {row["path"]: row for row in source_manifest}
    if len(manifest) != len(source_manifest): raise ValueError("duplicate source manifest paths")
    mapping = {row["source"]: row for row in proposal["mappings"]}
    candidates = {row["path"]: row for row in compilation["changes"]}
    if len(mapping) != len(proposal["mappings"]) or len(candidates) != len(compilation["changes"]):
        raise ValueError("duplicate transaction writes")
    targets = {path: mapping[path]["target"] if path in mapping else path for path in set(mapping) | set(candidates)}
    if len(targets) > 1000 or len({value.casefold() for value in targets.values()}) != len(targets):
        raise ValueError("bounded collision-free write set required")
    control = ".agentic_engineering_os_px/runtime-core/semantic-remaps"
    ledger_path = ".agentic_engineering_os_px/studios/semantic-remaps/resources.json"
    for path in (*targets, *targets.values(), control, ledger_path):
        _path(root, path)
        if not _scope_contains(scopes, path): raise ValueError("transaction write escapes exact admitted scopes")
    directory = root / control / compilation["compilation_sha256"]
    directory.parent.mkdir(parents=True, exist_ok=True)
    reject_path_links(directory)
    with FileLock(directory.parent / "transaction.lock", timeout_seconds=5):
        if directory.exists():
            raise ValueError("transaction already recorded; inspect its retained receipt and use explicit recovery")
        # Recheck every compiled source under the native transaction lock.
        for path, observation in manifest.items():
            raw = bytes(read_bounded_bytes(_path(root, path), max_bytes=MAX_FILE_BYTES))
            if len(raw) != observation["bytes"] or _image_sha(raw) != observation["sha256"]:
                raise ValueError("source changed after compiled transaction approval")
        for source, row in mapping.items():
            current = locators.get(row["entity_id"], "file")
            if current is None or current.locator_id != row["locator_id"] or current.revision != row["locator_revision"]:
                raise ValueError("canonical locator changed before remap")
            if _path(root, row["target"]).exists(): raise ValueError("target collision before apply")
        directory.mkdir()
        manager = ResourceManager(root / ledger_path)
        resource = manager.register_path(directory, allowed_cleanup_root=root / control,
            project_id=project_id, run_id=compilation["compilation_sha256"], lane_id="semantic-remap",
            creator="runtime.semantic_remap_transaction", classification=ResourceClassification.EVIDENCE,
            retention_required=True, expected_cleanup_event="verified_remap_and_explicit_retention_review")
        originals, outputs = {}, {}
        for source, target in sorted(targets.items()):
            original = bytes(read_bounded_bytes(_path(root, source), max_bytes=MAX_FILE_BYTES))
            originals[source] = original
            candidate = candidates.get(source)
            output = candidate["content"].encode("utf-8") if candidate else original
            if candidate and (candidate["before_sha256"] != _image_sha(original) or candidate["after_sha256"] != _image_sha(output) or candidate["target_path"] != target):
                raise ValueError("compiled rewrite image differs")
            outputs[target] = output
            _write_new(directory / (_image_sha(source.encode()) + ".before"), original)
        journal = {"schema_version": "px.semantic-remap-transaction/1.0", "status": "PREPARED",
            "project_id": project_id, "compilation_sha256": compilation["compilation_sha256"],
            "proposal_sha256": proposal["proposal_sha256"], "approval_sha256": approval_sha,
            "resource_id": resource.resource_id, "writes": [{"source": source, "target": target,
                "before_sha256": _image_sha(originals[source]), "after_sha256": _image_sha(outputs[target]),
                "backup": _image_sha(source.encode()) + ".before"} for source, target in sorted(targets.items())],
            "locator_before_sha256": hashlib.sha256(locators.snapshot_bytes()).hexdigest(),
            "git_starting_commit": "explicitly deferred by owner decision for this campaign",
            "authority_granted": False}
        _write_new(directory / "locator-before.json", locators.snapshot_bytes())
        _receipt(directory, journal)
        applied, removed = [], []
        try:
            for source, target in sorted(targets.items()):
                _replace_from_stage(_path(root, target), outputs[target], directory)
                applied.append(target)
            for source, row in sorted(mapping.items()):
                path = _path(root, source)
                if _image_sha(bytes(read_bounded_bytes(path, max_bytes=MAX_FILE_BYTES))) != _image_sha(originals[source]):
                    raise ValueError("source changed before exact remap removal")
                path.unlink(); removed.append(source)
            # Use a recovered, independent locator owner until commit publication succeeds.
            updated = locators.metadata_copy()
            for source, row in sorted(mapping.items()): updated.relocate(row["entity_id"], row["target"])
            after = updated.snapshot_bytes()
            _write_new(directory / "locator-after.json", after)
            return _receipt(directory, {**journal, "status": "APPLIED_PENDING_VERIFICATION",
                "locator_after_sha256": _image_sha(after), "locator_snapshot_path": (directory / "locator-after.json").relative_to(root).as_posix(),
                "verification": "deferred; no W2 fixed-point acceptance, tests, builds or installs claimed"})
        except Exception as error:
            conflicts = []
            for target in reversed(applied):
                path = _path(root, target)
                if not path.exists() or _image_sha(bytes(read_bounded_bytes(path, max_bytes=MAX_FILE_BYTES))) != _image_sha(outputs[target]):
                    conflicts.append(target); continue
                source = next(source for source, destination in targets.items() if destination == target)
                if source == target: _replace_from_stage(path, originals[source], directory)
                else: path.unlink()
            for source in removed:
                path = _path(root, source)
                if path.exists(): conflicts.append(source)
                else: _replace_from_stage(path, originals[source], directory)
            _receipt(directory, {**journal, "status": "ROLLBACK_CONFLICT" if conflicts else "ROLLED_BACK",
                                 "conflicts": conflicts, "error_type": type(error).__name__})
            raise
#: Directory holding retained remap transactions, relative to the project root.
REMAP_CONTROL_RELATIVE = ".agentic_engineering_os_px/runtime-core/semantic-remaps"


def recover_remap(root, compilation_sha256):
    """Inspect one retained remap transaction and report its true disposition.

    This is a read-only recovery probe: it reconstructs the transaction's durable
    state from its retained journal and receipts so an interrupted or partial
    apply is never silently assumed complete. It performs no write. A caller that
    must reverse a partial apply uses the returned `recovery_action` and the
    retained `*.before` images, under its own explicit admission.
    """
    reject_path_links(Path(root))
    root = Path(root).resolve(strict=True)
    if type(compilation_sha256) is not str or not compilation_sha256.strip():
        raise ValueError("recovery requires the exact compilation digest")
    directory = _path(root, REMAP_CONTROL_RELATIVE) / compilation_sha256
    if not directory.is_dir():
        return {"schema_version": "px.semantic-remap-recovery/1.0",
                "status": "NO_RETAINED_TRANSACTION", "compilation_sha256": compilation_sha256,
                "authority_granted": False}
    journal = load_json_object(directory / "receipt.json", max_bytes=MAX_PLAN_BYTES)
    status = str(journal.get("status") or "UNKNOWN")
    writes = journal.get("writes") or []
    if not isinstance(writes, list):
        raise ValueError("retained transaction journal is malformed")
    present, missing, mismatched = [], [], []
    for row in writes:
        target = _path(root, str(row["target"]))
        if not target.exists():
            missing.append(row["target"])
            continue
        image = _image_sha(bytes(read_bounded_bytes(target, max_bytes=MAX_FILE_BYTES)))
        if image == row.get("after_sha256"):
            present.append(row["target"])
        else:
            mismatched.append(row["target"])
    if status in {"PREPARED", "ROLLED_BACK"}:
        recovery_action = "none"
    elif status == "APPLIED_PENDING_VERIFICATION" and not missing and not mismatched:
        recovery_action = "activate_locator_snapshot"
    elif missing or mismatched:
        recovery_action = "rollback_from_retained_images"
    else:
        recovery_action = "review"
    body = {
        "schema_version": "px.semantic-remap-recovery/1.0",
        "status": status,
        "compilation_sha256": compilation_sha256,
        "applied_targets": sorted(present),
        "missing_targets": sorted(missing),
        "mismatched_targets": sorted(mismatched),
        "recovery_action": recovery_action,
        "retained_directory": directory.relative_to(root).as_posix(),
        "authority_granted": False,
    }
    return {**body, "recovery_sha256": _hash(body)}


def activate_remap(root, compilation_sha256, locators, entities):
    """Publish a completed remap's locator snapshot through the canonical owner.

    Activation is the final step that makes the new locations canonical. It
    refuses unless the retained transaction is a complete, verified apply, and it
    re-derives every identity from the canonical entity owner before publishing.
    It returns a new, independent locator owner; the caller persists it through
    its own owned path.
    """
    reject_path_links(Path(root))
    root = Path(root).resolve(strict=True)
    if type(locators) is not LocatorRegistry:
        raise TypeError("activation requires the native locator owner")
    from .semantic_entity import EntityRegistry
    if type(entities) is not EntityRegistry:
        raise TypeError("activation requires the native entity owner")
    recovery = recover_remap(root, compilation_sha256)
    if recovery["status"] == "NO_RETAINED_TRANSACTION":
        raise ValueError("activation requires a retained completed transaction")
    if recovery["recovery_action"] != "activate_locator_snapshot":
        raise ValueError("transaction is not a complete verified apply: " + recovery["recovery_action"])
    directory = _path(root, REMAP_CONTROL_RELATIVE) / compilation_sha256
    after = bytes(read_bounded_bytes(directory / "locator-after.json", max_bytes=MAX_PLAN_BYTES))
    activated = LocatorRegistry.from_snapshot_bytes(entities, after)
    # The activated snapshot must agree with the recorded digest, so a tampered
    # after-image cannot be published as canonical.
    if _image_sha(activated.snapshot_bytes()) != _image_sha(after):
        raise ValueError("activated locator snapshot does not round-trip")
    return activated