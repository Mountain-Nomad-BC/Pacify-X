"""Canonical mutable personal records, explicit consent/purpose and erasure fences.

Only this store's live payload is erasable. No old vault, provider, backup or
immutable evidence is silently treated as erased. Signed policies describe owner
decisions; the software neither supplies them nor asserts their legal validity.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
from uuid import uuid4

from .archive_io import reject_path_links
from .data_subject_records import CONTROL_ROOT, _approved, _digest, _relative, _consume_request_approval
from .effect_intent import EffectIntentLedger
from .file_lock import FileLock
from .json_io import bounded_canonical_json_bytes, load_json_object
from .scope_lease import ScopeLeaseStore
from .studio_authority import StudioAuthorityStore

SCHEMA = "px.personal-record-request/1.1"
STORE = CONTROL_ROOT + "/personal-records.json"
OPERATIONS = {"personal-create", "personal-access", "personal-export", "personal-erase", "personal-retention",
              "personal-use", "personal-rectify", "personal-withdraw-consent"}
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RESIDUALS = ["historical MemoryVault/T.I.E.", "provider-side copies", "external exports/backups",
             "OS snapshots, storage media remnants", "immutable operational evidence",
             "owner-selected request files and unsaved response documents", "pseudonymous control hashes/tombstones"]


def _authority(root, request):
    policy_locator = _relative(request["policy_locator"])
    authority = StudioAuthorityStore.open_existing(root)
    policy = _approved(authority, root, policy_locator, "px.data-control-policy/1.0")
    if (policy.get("subject_id") != request["subject_id"] or
            request["requester_id"] not in policy.get("authorized_requesters", []) or
            request["operation"] not in policy.get("allowed_operations", []) or
            policy.get("owner") != "runtime.personal_record_store"):
        raise PermissionError("approved personal policy does not cover this owner/subject/operation")
    purposes = policy.get("operation_purposes")
    if (type(purposes) is not dict or set(purposes) - OPERATIONS or
            any(type(values) is not list or not values or any(type(value) is not str or not value for value in values)
                for values in purposes.values()) or request["purpose"] not in purposes.get(request["operation"], [])):
        raise PermissionError("explicit operation-purpose owner policy missing or exceeded")
    operation = request["operation"]
    effects = ("read", "write")
    if operation in {"personal-erase", "personal-retention", "personal-rectify"}:
        effects += ("destructive",)
    grant, grant_digest = authority.resolve_grant(request["grant_id"],
        subject_id=request["requester_id"], required_effects=effects)
    if not any(STORE == _relative(s) or STORE.startswith(_relative(s) + "/") for s in grant["scope_roots"]):
        raise PermissionError("native personal grant does not cover canonical store")
    for required in (CONTROL_ROOT, ".agentic_engineering_os_px/runtime-core", ".agentic_engineering_os_px/resource-lifecycle",
                     ".agentic_engineering_os_px/studios/authority"):
        if not any(required == _relative(s) or required.startswith(_relative(s) + "/") for s in grant["scope_roots"]):
            raise PermissionError("native personal grant omits custody scope " + required)
    if "destructive" in effects:
        if policy.get("legal_hold") is not False:
            raise PermissionError("personal content removal/replacement requires explicit no-hold owner decision")
    return authority, policy, grant_digest


def _load(root, authority, intents):
    path = root / STORE
    reject_path_links(path)
    anchor = intents.resume_from(execution_id="personal-record-store", name="current-head")
    if not path.exists():
        if anchor is not None:
            raise PermissionError("canonical personal store is missing against durable head")
        return {"schema_version": "px.personal-record-store/1.0", "generation": 0,
                "records": {}, "tombstones": {}}
    image = load_json_object(path, max_bytes=4 * 1024 * 1024)
    state = authority.verify_receipt(image)
    if (state.get("schema_version") != "px.personal-record-store/1.0" or
            type(state.get("records")) is not dict or type(state.get("tombstones")) is not dict):
        raise ValueError("canonical personal store schema invalid")
    if (anchor is None or anchor["state"].get("image_sha256") != _digest(image) or
            anchor["state"].get("generation") != state.get("generation")):
        raise PermissionError("personal store head differs; recovery required, never replay")
    fence = intents.fence(anchor["state"].get("intent_key", "missing-current-head"))
    if fence["disposition"] != "committed" or fence.get("result_sha256") != _digest(image):
        raise PermissionError("personal publication outcome uncertain; recovery required")
    return state


def _consent_key(subject_id, reference):
    return _digest({"subject_id": subject_id, "consent_reference": reference})


def _content_allowed(content, policy):
    allowed = policy.get("allowed_content_fields")
    if (type(content) is not dict or type(allowed) is not list or not allowed or
            any(type(field) is not str for field in allowed) or set(content) - set(allowed) or
            policy.get("data_class") not in {"personal", "sensitive"}):
        raise PermissionError("personal record minimization/classification policy missing or exceeded")


def _publish(root, authority, intents, state, request, validate):
    from .resource_lifecycle import ResourceManager, RunState
    from .studio_models import write_json_atomic
    execution = "personal-control-" + uuid4().hex
    key = "personal-control:" + hashlib.sha256(request["idempotency_key"].encode("utf-8")).hexdigest()
    leases = ScopeLeaseStore(root)
    lease = "lease-" + execution
    leases.acquire(lease_id=lease, execution_id=execution, effect="write", scopes=(CONTROL_ROOT,),
        reason="explicitly approved personal data operation", expires_utc=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat())
    manager = None
    workspace = None
    intended = published = False
    primary_error = None
    try:
        if intents.fence(key)["disposition"] != "new":
            raise PermissionError("personal operation replay or uncertain outcome refused")
        validate()
        intents.intend(idempotency_key=key, execution_id=execution, effect="write", scopes=(STORE,))
        intended = True
        state["generation"] += 1
        state["last_operation"] = {"request_sha256": _digest({k: v for k, v in request.items() if k != "approval_capability"}),
            "approval_nonce_sha256": hashlib.sha256(request["approval_capability"]["claim"]["nonce"].encode("utf-8")).hexdigest(),
            "operation": request["operation"], "execution_id": execution}
        signed = authority.sign_receipt(state)
        parent = root / ".agentic_engineering_os_px/resource-lifecycle/personal-workspaces"
        reject_path_links(parent)
        parent.mkdir(parents=True, exist_ok=True)
        manager = ResourceManager(root / ".agentic_engineering_os_px/resource-lifecycle/resources.json",
            receipt_dir=root / ".agentic_engineering_os_px/resource-lifecycle/cleanup-receipts")
        workspace = manager.create_workspace(parent, project_id=str(root), run_id=execution,
            lane_id="personal-data-control", creator="personal-record-store", prefix=".personal-control-")
        prepared = Path(workspace.path) / "records.json"
        write_json_atomic(prepared, signed)
        target = root / STORE
        reject_path_links(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        validate()
        os.replace(prepared, target)
        published = True
        image_digest = _digest(signed)
        intents.checkpoint(execution_id="personal-record-store", name="current-head",
            state={"generation": state["generation"], "image_sha256": image_digest, "intent_key": key})
        intents.commit(idempotency_key=key, execution_id=execution, result_sha256=image_digest)
    except BaseException as error:
        primary_error = error
        if intended and not published:
            try:
                intents.fail(idempotency_key=key, execution_id=execution, failure_type=type(error).__name__)
            except BaseException as failure:
                BaseException.add_note(error, "personal intent failure settlement uncertain: " + repr(failure))
        raise
    finally:
        errors = []
        try:
            if workspace is not None:
                cleanup = manager.reclaim_ephemeral_path(workspace.resource_id,
                    reason="personal record operation settled", state=RunState.COMPLETED if published else RunState.FAILED)
                if cleanup.resources_failed or cleanup.errors:
                    raise RuntimeError("personal temporary custody did not close")
        except BaseException as error:
            errors.append(error)
        try:
            leases.release(lease_id=lease, execution_id=execution)
        except BaseException as error:
            errors.append(error)
        if errors:
            if primary_error is None:
                raise RuntimeError("personal custody closure uncertain") from errors[0]
            for error in errors:
                BaseException.add_note(primary_error, "personal custody closure uncertain: " + repr(error))
    return {"execution_id": execution, "intent_key": key, "generation": state["generation"],
            "image_sha256": image_digest, "cleanup_receipt_id": cleanup.cleanup_id}


def personal_record_request(project_root: Path, request: dict, *, materialize_use=None) -> dict:
    fields = {"schema_version", "operation", "requester_id", "subject_id", "grant_id",
              "policy_locator", "approval_capability", "purpose"}
    operation = request.get("operation") if type(request) is dict else None
    if materialize_use is not None and (operation != "personal-use" or not callable(materialize_use)):
        raise ValueError("internal materializer requires personal-use")
    mutate = operation not in {"personal-access", "personal-export", "personal-use"}
    if mutate:
        fields |= {"idempotency_key"}
    if operation == "personal-create":
        fields |= {"record"}
    if operation == "personal-rectify":
        fields |= {"record_id", "expected_generation", "replacement_content"}
    if operation == "personal-withdraw-consent":
        fields |= {"consent_reference", "expected_generation"}
    if (type(request) is not dict or set(request) != fields or operation not in OPERATIONS or
            request.get("schema_version") != SCHEMA or any(type(request[k]) is not str or
            not request[k] or len(request[k]) > 512 for k in fields - {"record", "approval_capability", "expected_generation", "replacement_content"})):
        raise ValueError("closed bounded personal control request required")
    if "expected_generation" in fields and (type(request["expected_generation"]) is not int or
            not 0 <= request["expected_generation"] <= 1000000000):
        raise ValueError("exact bounded expected generation required")
    bounded_canonical_json_bytes(request, max_bytes=256 * 1024)
    root = Path(project_root)
    reject_path_links(root)
    root = root.resolve(strict=True)
    authority, policy, grant_digest = _authority(root, request)
    _consume_request_approval(authority, request)
    intents = EffectIntentLedger(root)
    def validate():
        _, current_policy, current_grant = _authority(root, request)
        if current_policy != policy or current_grant != grant_digest:
            raise PermissionError("personal policy/grant changed at effect boundary")
    # The native lock serializes read snapshots, erase, and recreation attempts.
    # Read operations also require a native write grant for lock custody.
    with FileLock(root / CONTROL_ROOT / ".personal-records.lock"):
        state = _load(root, authority, intents)
        # Older signed mutable stores have no withdrawal map. Normalize only
        # after validating their actual signed image/head; persist on mutation.
        withdrawn = state.setdefault("withdrawn_consents", {})
        if type(withdrawn) is not dict:
            raise ValueError("canonical withdrawal registry invalid")
        if "expected_generation" in request and state["generation"] != request["expected_generation"]:
            raise PermissionError("personal control expected generation is stale")
        selected = {key: value for key, value in state["records"].items()
                    if value["subject_id"] == request["subject_id"]}
        if operation == "personal-create":
            row = request["record"]
            required = {"record_id", "purpose", "consent_reference", "content"}
            if (type(row) is not dict or set(row) != required or type(row["record_id"]) is not str or
                    ID.fullmatch(row["record_id"]) is None or type(row["content"]) is not dict or
                    row["purpose"] != request["purpose"] or
                    row["purpose"] not in policy.get("approved_purposes", []) or
                    row["consent_reference"] not in policy.get("approved_consent_references", [])):
                raise PermissionError("record purpose/consent lacks explicit approved policy binding")
            _content_allowed(row["content"], policy)
            if _consent_key(request["subject_id"], row["consent_reference"]) in withdrawn:
                raise PermissionError("withdrawn subject/consent cannot be recreated")
            erased_key = hashlib.sha256(row["record_id"].encode("utf-8")).hexdigest()
            if row["record_id"] in state["records"] or erased_key in state["tombstones"]:
                raise PermissionError("existing or erased record identity cannot be recreated")
            state["records"][row["record_id"]] = {**row, "subject_id": request["subject_id"],
                "created_utc": datetime.now(timezone.utc).isoformat(), "policy_sha256": _digest(policy),
                "data_class": policy["data_class"], "consent_status": "active"}
            affected = 1
        elif operation == "personal-rectify":
            value = selected.get(request["record_id"])
            if value is None:
                raise PermissionError("rectification requires an actual live subject record; erased identities remain fenced")
            _content_allowed(request["replacement_content"], policy)
            value["content"] = request["replacement_content"]
            value["rectified_utc"] = datetime.now(timezone.utc).isoformat()
            value["rectification_policy_sha256"] = _digest(policy)
            affected = 1
        elif operation == "personal-withdraw-consent":
            matches = [value for value in selected.values() if value["consent_reference"] == request["consent_reference"]]
            if not matches:
                raise PermissionError("withdrawal requires an actual subject-bound consent reference")
            key = _consent_key(request["subject_id"], request["consent_reference"])
            withdrawn[key] = {"withdrawn_utc": datetime.now(timezone.utc).isoformat(), "policy_sha256": _digest(policy)}
            for value in matches:
                value["consent_status"] = "withdrawn"
            affected = len(matches)
        elif operation in {"personal-erase", "personal-retention"}:
            now = datetime.now(timezone.utc)
            days = policy.get("retention_days")
            if operation == "personal-retention" and (type(days) is not int or not 0 <= days <= 365000):
                raise PermissionError("retention requires explicit approved bounded days")
            affected = 0
            for key, value in selected.items():
                created = datetime.fromisoformat(value["created_utc"])
                if created.tzinfo is None or created > now:
                    raise ValueError("canonical personal record time invalid")
                if operation == "personal-retention" and now - created <= timedelta(days=days):
                    continue
                # No content, subject name, purpose or consent text in tombstones.
                tombstone_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
                state["tombstones"][tombstone_key] = {"erased_utc": now.isoformat(),
                    "operation": operation, "policy_sha256": _digest(policy)}
                del state["records"][key]
                affected += 1
        else:
            if operation == "personal-use":
                if any(_consent_key(request["subject_id"], value["consent_reference"]) in withdrawn or
                       value.get("consent_status", "active") != "active" or
                       value["consent_reference"] not in policy.get("approved_consent_references", []) or
                       value["purpose"] != request["purpose"] or value["purpose"] not in policy.get("approved_purposes", [])
                       for value in selected.values()):
                    raise PermissionError("operational use blocked by withdrawn consent or current purpose/consent policy")
                for value in selected.values():
                    _content_allowed(value["content"], policy)
            validate()
            response = {"schema_version": "px.personal-control-response/1.0", "operation": operation,
                "records": list(selected.values()), "record_count": len(selected),
                "generation": state["generation"], "authorized_purpose": request["purpose"],
                "control_semantics": "operational_use" if operation == "personal-use" else "explicit_policy_permitted_rights_access",
                "coverage_complete": False, "legal_signoff_asserted": False, "residual_surfaces": RESIDUALS}
            anchor = intents.resume_from(execution_id="personal-record-store", name="current-head")
            response["source_image_sha256"] = anchor["state"]["image_sha256"] if anchor else None
            if materialize_use is None:
                return response
            execution = "personal-context-" + uuid4().hex
            leases = ScopeLeaseStore(root)
            lease = "lease-" + execution
            leases.acquire(lease_id=lease, execution_id=execution, effect="read", scopes=(STORE,),
                reason="approved ephemeral personal-use materialization",
                expires_utc=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat())
            materialization_error = None
            try:
                validate()
                result = materialize_use(response)
                validate()
                _load(root, authority, intents)
                if intents.resume_from(execution_id="personal-record-store", name="current-head") != anchor:
                    raise PermissionError("personal source changed during materialization")
                return result
            except BaseException as error:
                materialization_error = error
                raise
            finally:
                try:
                    if not leases.release(lease_id=lease, execution_id=execution):
                        raise RuntimeError("personal context lease did not close")
                except BaseException as error:
                    if materialization_error is None:
                        raise
                    BaseException.add_note(materialization_error, "personal context lease closure failed: " + repr(error))
        receipt = _publish(root, authority, intents, state, request, validate)
        return {"schema_version": "px.personal-control-response/1.0", "operation": operation,
            "affected_count": affected, "receipt": receipt, "coverage_complete": False,
            "content_erased": operation in {"personal-erase", "personal-retention"},
            "withdrawal_semantics": "operational_use_blocked_live_payload_retained_pending_approved_erasure" if operation == "personal-withdraw-consent" else None,
            "legal_signoff_asserted": False, "erasure_scope": "canonical personal store live content only",
            "residual_surfaces": RESIDUALS}
