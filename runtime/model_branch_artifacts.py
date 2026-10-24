"""Immutable branch output commitment before peer visibility, under native custody."""
from pathlib import Path
import hashlib
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .effect_intent import EffectIntentLedger
from .scope_lease import ScopeLeaseStore

from .archive_io import reject_path_links
from .file_lock import FileLock
from .json_io import bounded_canonical_json_bytes, load_json_object, read_bounded_bytes
from .resource_lifecycle import ResourceManager, ResourceClassification
from .task_execution_plan import task_execution_plan_from_dict, validate_task_execution_plan


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _publish_exact(path, raw):
    reject_path_links(path)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if bytes(read_bounded_bytes(path, max_bytes=len(raw) + 1)) != raw:
            raise ValueError("immutable branch artifact collision") from None


def _artifact_directory(root, invocation, run_id):
    from .model_group_preparation import MemberExecutionInput
    if type(invocation) is not MemberExecutionInput:
        raise TypeError("native prepared member invocation required")
    if type(run_id) is not str or not run_id.strip() or len(run_id) > 256:
        raise ValueError("bounded execution identity required")
    return (root / ".agentic_engineering_os_px/runtime-core/model-artifacts"
        / invocation.task_plan_sha256 / _sha(run_id.encode())
        / _sha((invocation.model_id + "\0" + invocation.agent_generation_id).encode()))


def _artifact_intent_key(invocation, run_id):
    image = {"task_plan_sha256": invocation.task_plan_sha256, "run_id": run_id,
        "model_id": invocation.model_id, "agent_generation_id": invocation.agent_generation_id,
        "attachment_sha256": invocation.attachment.attachment_sha256,
        "context_sha256": invocation.context_sha256}
    return "branch-artifact-" + _sha(bounded_canonical_json_bytes(image, max_bytes=16384))


def _require_native_commitment(root, invocation, run_id, artifact_sha256):
    directory = _artifact_directory(root, invocation, run_id)
    proof = EffectIntentLedger(root).fence(_artifact_intent_key(invocation, run_id))
    if (proof.get("disposition") != "committed" or proof.get("execution_id") != run_id
            or proof.get("effect") != "write"
            or proof.get("scopes") != [directory.relative_to(root).as_posix()]
            or proof.get("result_sha256") != artifact_sha256):
        raise ValueError("native branch commitment proof is missing or differs")


def commit_branch_artifact(root, task_plan, invocation, value, *, run_id):
    """Commit internal evidence under exact immutable run/member custody.

    This bookkeeping grants no user effect authority. Its runtime caller must
    already admit the actual member execution; no W0 work admission is invented.
    """
    reject_path_links(Path(root))
    root = Path(root).resolve(strict=True)
    directory = _artifact_directory(root, invocation, run_id)
    plan = task_execution_plan_from_dict(task_plan)
    if not validate_task_execution_plan(plan)["valid"] or plan.model_execution_group is None:
        raise ValueError("branch commitment requires intact canonical group plan")
    from .model_group_preparation import member_attachment, member_execution_input
    _, member = member_attachment(task_plan, invocation.model_id)
    if member_execution_input(task_plan, member) != invocation:
        raise ValueError("artifact invocation differs from exact prepared member")
    branch = next(b for b in plan.model_execution_group.branches if b.model_id == invocation.model_id)
    raw = bounded_canonical_json_bytes(value, max_bytes=branch.work_contract.max_output_bytes)
    reject_path_links(directory)
    intent_key = _artifact_intent_key(invocation, run_id)
    intents = EffectIntentLedger(root)
    disposition = intents.fence(intent_key).get("disposition")
    output, manifest = directory / "output.json", directory / "commitment.json"
    if disposition == "committed":
        previous = load_json_object(manifest, max_bytes=16384)
        artifact = {**previous, "manifest_path": manifest.relative_to(root).as_posix()}
        if read_branch_artifact(root, artifact, invocation, run_id=run_id) != raw:
            raise ValueError("immutable branch artifact collision")
        return artifact
    if disposition != "new":
        raise ValueError("uncertain branch artifact requires native reconciliation before retry")
    leases = ScopeLeaseStore(root)
    lease_id = "branch-artifact-lease-" + uuid4().hex
    scopes = (directory.relative_to(root).as_posix(),)
    leases.acquire(lease_id=lease_id, execution_id=run_id, effect="write", scopes=scopes,
        reason="immutable prepared branch evidence commitment",
        expires_utc=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
    primary_error = None
    intended = False
    images_written = False
    try:
        # Recheck after acquiring the physical owner; no legacy/orphan evidence
        # is backfilled into a current successful intent.
        if intents.fence(intent_key).get("disposition") != "new":
            raise ValueError("branch artifact intent changed; reconciliation required")
        if output.exists() or manifest.exists():
            raise ValueError("unfenced branch artifact requires native reconciliation")
        intents.intend(idempotency_key=intent_key, execution_id=run_id, effect="write", scopes=scopes)
        intended = True
        directory.mkdir(parents=True, exist_ok=True)
        reject_path_links(directory)
        base = root / ".agentic_engineering_os_px/runtime-core/model-artifacts"
        with FileLock(directory / ".commit.lock", timeout_seconds=10):
            manager = ResourceManager(root / ".agentic_engineering_os_px/studios/agents/resources.json")
            path_matches = [record for record in manager.ledger.load()
                            if record.path == str(directory.absolute())]
            matches = [record for record in path_matches if record.run_id == run_id
                and record.project_id == plan.project_id
                and record.creator == "runtime.model_branch_artifacts"
                and record.retention_required
                and record.classification == ResourceClassification.EVIDENCE.value]
            if len(matches) > 1 or len(matches) != len(path_matches):
                raise ValueError("branch evidence custody is ambiguous or differs")
            resource = matches[0] if matches else manager.register_path(directory,
                allowed_cleanup_root=base, project_id=plan.project_id, run_id=run_id,
                lane_id="model-branch:" + invocation.model_id, creator="runtime.model_branch_artifacts",
                classification=ResourceClassification.EVIDENCE, retention_required=True,
                expected_cleanup_event="explicit_evidence_retention_review")
            body = {"schema_version": "px.model-branch-artifact/1.0", "project_id": plan.project_id,
                "run_id": run_id, "task_plan_id": plan.plan_id, "task_plan_sha256": plan.plan_sha256,
                "group_sha256": invocation.group_sha256, "model_id": invocation.model_id,
                "agent_generation_id": invocation.agent_generation_id,
                "attachment_sha256": invocation.attachment.attachment_sha256,
                "context_sha256": invocation.context_sha256, "output_sha256": _sha(raw),
                "output_bytes": len(raw), "output_path": output.relative_to(root).as_posix(),
                "resource_id": resource.resource_id, "authority_granted": False}
            body["artifact_sha256"] = _sha(bounded_canonical_json_bytes(body, max_bytes=16384))
            from .contracts import validate_instance
            validate_instance(body, Path(__file__).resolve().parents[1] / "contracts/models/model-branch-artifact.schema.json")
            manifest_raw = bounded_canonical_json_bytes(body, max_bytes=16384)
            _publish_exact(output, raw)
            _publish_exact(manifest, manifest_raw)
            if (bytes(read_bounded_bytes(output, max_bytes=len(raw) + 1)) != raw
                    or bytes(read_bounded_bytes(manifest, max_bytes=len(manifest_raw) + 1)) != manifest_raw):
                raise ValueError("published branch images differ from exact commitment")
            images_written = True
            intents.commit(idempotency_key=intent_key, execution_id=run_id,
                           result_sha256=body["artifact_sha256"])
            return {**body, "manifest_path": manifest.relative_to(root).as_posix()}
    except BaseException as error:
        primary_error = error
        if intended and not images_written:
            try:
                intents.fail(idempotency_key=intent_key, execution_id=run_id,
                             failure_type=type(error).__name__)
            except BaseException as settlement_error:
                _note_failure(error, "branch artifact intent settlement", settlement_error)
        raise
    finally:
        try:
            leases.release(lease_id=lease_id, execution_id=run_id)
        except BaseException as release_error:
            if primary_error is None:
                raise
            _note_failure(primary_error, "branch artifact lease release", release_error)


def _note_failure(primary, phase, error):
    try:
        BaseException.add_note(primary, phase + " remains uncertain: " +
                               type(error).__name__ + ": " + str(error))
    except BaseException:
        pass


def read_branch_artifact(root, artifact, invocation, *, run_id):
    """Read committed bytes only after exact plan/generation/member binding."""
    reject_path_links(Path(root))
    root = Path(root).resolve(strict=True)
    directory = _artifact_directory(root, invocation, run_id)
    if artifact.get("manifest_path") != (directory / "commitment.json").relative_to(root).as_posix():
        raise ValueError("artifact manifest differs from canonical branch custody location")
    from .input_files import contained_file
    manifest, _ = contained_file(root, artifact["manifest_path"])
    body = load_json_object(manifest, max_bytes=16384)
    from .contracts import validate_instance
    validate_instance(body, Path(__file__).resolve().parents[1] / "contracts/models/model-branch-artifact.schema.json")
    expected = {"task_plan_sha256": invocation.task_plan_sha256, "group_sha256": invocation.group_sha256,
        "model_id": invocation.model_id, "agent_generation_id": invocation.agent_generation_id,
        "attachment_sha256": invocation.attachment.attachment_sha256, "context_sha256": invocation.context_sha256,
        "run_id": run_id}
    if any(body.get(k) != v for k, v in expected.items()) or body.get("authority_granted") is not False:
        raise ValueError("committed artifact generation/member binding differs")
    unsigned = {k: v for k, v in body.items() if k != "artifact_sha256"}
    if body.get("artifact_sha256") != _sha(bounded_canonical_json_bytes(unsigned, max_bytes=16384)):
        raise ValueError("committed artifact digest differs")
    if {**body, "manifest_path": artifact["manifest_path"]} != artifact:
        raise ValueError("artifact reference differs from committed manifest")
    if body["output_path"] != (directory / "output.json").relative_to(root).as_posix():
        raise ValueError("artifact output differs from canonical branch custody location")
    _require_native_commitment(root, invocation, run_id, body["artifact_sha256"])
    manager = ResourceManager(root / ".agentic_engineering_os_px/studios/agents/resources.json")
    resource = next((record for record in manager.ledger.observe()
                     if record.resource_id == body["resource_id"]), None)
    if (resource is None or resource.classification != ResourceClassification.EVIDENCE.value
            or not resource.retention_required or resource.run_id != run_id
            or resource.project_id != body["project_id"]
            or resource.creator != "runtime.model_branch_artifacts"
            or resource.path != str(directory.absolute())
            or resource.path_identity is None
            or tuple(resource.path_identity) != manager._path_identity(directory)):
        raise ValueError("native retained artifact custody is missing or differs")
    output, _ = contained_file(root, body["output_path"])
    raw = bytes(read_bounded_bytes(output, max_bytes=524288))
    if len(raw) != body["output_bytes"] or _sha(raw) != body["output_sha256"]:
        raise ValueError("committed output image differs")
    return raw
