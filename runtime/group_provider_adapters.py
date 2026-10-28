"""Bounded configured factory for native prepared-group provider adapters.

Configuration references exact native profiles; it cannot declare endpoints,
Python imports, executable code, model bytes, or provider admission. Only the
implemented llama.cpp router stream is supported. Other services stay absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
import json
import os

from .model_profile import ModelRuntimeProfile, load_runtime_profiles
from .provider_gateway import LlamaCppStreamingHttpAdapter, load_provider_registry
from .archive_io import reject_path_links
from .remote_model_attachment import RemoteModelAttachment, build_remote_model_attachment


@dataclass(frozen=True, slots=True)
class RemoteGroupProviderBinding:
    attachment: RemoteModelAttachment
    adapter: object
    policy_json: str
    assert_current: Callable[[], None]

    @property
    def policy(self):
        return json.loads(self.policy_json)

    @property
    def adapter_id(self):
        return self.adapter.adapter_id


def _remote_binding(engine_root, project_root, model_id, row):
    from .remote_provider_profiles import load_profiles
    from .remote_provider_adapters import remote_adapter_for
    from .json_io import load_json_object
    attachment = build_remote_model_attachment(project_root, profile_id=row['profile_id'], requester_id=row['requester_id'])
    if attachment.model_id != model_id or attachment.attachment_sha256 != row['attachment_sha256'] or attachment.budget_id != row['budget_id'] or attachment.adapter_id != row['adapter_id']:
        raise PermissionError('configured remote attachment differs from prepared binding')
    authority, profiles = load_profiles(project_root)
    profile = next(item for item in profiles if item['profile_id'] == attachment.profile_id)
    path = project_root / attachment.policy_locator
    reject_path_links(path)
    policy = authority.verify_receipt(load_json_object(path, max_bytes=256 * 1024))
    model = policy.get('model', {})
    if (model.get('attachment_sha256') != attachment.attachment_sha256 or
            model.get('model_id') != attachment.provider_model_id or model.get('model_revision') != attachment.model_revision or
            model.get('provider_id') != attachment.provider_id or model.get('adapter_id') != attachment.adapter_id or
            model.get('privacy') != attachment.privacy or model.get('authority_class') != attachment.authority_class or
            policy.get('authority', {}).get('revision') != attachment.grant_revision or
            policy.get('egress', {}).get('mode') != 'allowlist' or
            policy.get('egress', {}).get('allowed_destinations') != [attachment.origin] or
            policy.get('cost', {}).get('budget_id') != attachment.budget_id):
        raise PermissionError('signed remote policy differs from exact service attachment/grant/egress')
    policy_json = json.dumps(policy, sort_keys=True, separators=(',', ':'), allow_nan=False)

    def current():
        if build_remote_model_attachment(project_root, profile_id=row['profile_id'], requester_id=row['requester_id']) != attachment:
            raise PermissionError('remote signed profile/grant changed')
        registry = load_provider_registry(engine_root)
        entries = [item for item in registry['adapters'] if item['adapter_id'] == row['adapter_id']]
        if len(entries) != 1 or entries[0].get('admitted') is not True or entries[0].get('status') != 'ready' or entries[0].get('provider_id') != attachment.provider_id:
            raise PermissionError('remote provider adapter is not admitted/current')
        reject_path_links(path)
        if authority.verify_receipt(load_json_object(path, max_bytes=256 * 1024)) != policy:
            raise PermissionError('remote signed provider policy changed')

    current()
    adapter = remote_adapter_for(profile, credential_resolver=lambda reference: os.environ.get(reference), validate_current=current)
    return RemoteGroupProviderBinding(attachment, adapter, policy_json, current)


@dataclass(frozen=True, slots=True)
class GroupProviderBinding:
    model_id: str
    artifact_sha256: str
    profile: ModelRuntimeProfile
    adapter: LlamaCppStreamingHttpAdapter
    session_id: str
    budget_id: str
    assert_current: Callable[[], None]

    @property
    def adapter_id(self) -> str:
        return self.adapter.adapter_id


def build_group_adapter_resolver(
    engine_root: Path, project_root: Path, configuration: Mapping[str, object],
) -> Callable[[str], GroupProviderBinding | None]:
    """Build a resolver from bounded JSON, not impossible JSON callable objects."""
    if type(configuration) is not dict or set(configuration) != {"schema_version", "adapters"}:
        raise ValueError("group adapter configuration requires exact versioned fields")
    if configuration["schema_version"] != "px.group-provider-adapters/1.0":
        raise ValueError("unsupported group adapter configuration version")
    rows = configuration["adapters"]
    if type(rows) is not dict or not 1 <= len(rows) <= 128:
        raise ValueError("group adapter configuration must contain a bounded model mapping")
    frozen: dict[str, dict[str, str]] = {}
    for model_id, row in rows.items():
        if type(model_id) is not str or not model_id or len(model_id.encode()) > 256:
            raise ValueError("configured group model identity is invalid")
        remote = isinstance(row, dict) and row.get('kind') in {'custom_openai_chat', 'remote_provider'}
        fields = {"kind", "profile_id", "adapter_id", "budget_id"}
        if remote:
            fields |= {'requester_id', 'attachment_sha256'}
        if type(row) is not dict or set(row) != fields:
            raise ValueError("group adapter entries cannot declare code or endpoints")
        if not ((row["kind"] == "llama_cpp_router" and row["adapter_id"] == "llama-cpp-stream") or
                (remote and (row['kind'] == 'remote_provider' or row['adapter_id'] == 'custom-openai-chat'))):
            raise ValueError("configured group provider path is not implemented")
        if any(type(value) is not str or not value.strip() or len(value.encode()) > 256 or
               any(ord(c) < 32 for c in value) for value in row.values()):
            raise ValueError("group adapter reference must be bounded text")
        frozen[model_id] = dict(row)
    reject_path_links(engine_root)
    reject_path_links(project_root)
    engine_root = engine_root.resolve(strict=True)
    project_root = project_root.resolve(strict=True)

    def resolve(model_id: str) -> GroupProviderBinding | None:
        row = frozen.get(model_id)
        if row is None:
            return None
        if row['kind'] in {'custom_openai_chat', 'remote_provider'}:
            return _remote_binding(engine_root, project_root, model_id, row)
        # Reuse the actual native certified-profile/running-router discovery.
        from .vscode_model_bridge import _current_router
        from .resource_lifecycle import _process_start_fingerprint, _host_boot_generation
        profiles = [item for item in load_runtime_profiles(engine_root) if item.profile_id == row["profile_id"]]
        if len(profiles) != 1 or not profiles[0].is_certified:
            raise PermissionError("configured group profile is not exactly certified")
        profile = profiles[0]
        if profile.model_id != model_id:
            raise PermissionError("configured group profile refers to a different model")
        running = _current_router(project_root)
        if running is None:
            raise PermissionError("configured group has no running native router")
        runtime, session_id, plan = running
        if plan.get("schema_version") != "px.local-model-router-pool-plan/1.1":
            raise PermissionError("configured group requires profile-bound router plan 1.1")
        admissions = [item for item in plan["models"] if item.get("model_id") == model_id]
        binding = plan.get("preset_binding")
        bound_profiles = binding.get("models") if type(binding) is dict else None
        if type(bound_profiles) is not list:
            raise PermissionError("configured group router has no frozen profile binding")
        bound = [item for item in bound_profiles if item.get("model_id") == model_id]
        if len(admissions) != 1 or len(bound) != 1 or bound[0].get("profile_sha256") != profile.profile_sha256:
            raise PermissionError("configured group profile differs from native running router binding")
        model_sha = admissions[0]["admission"]["model_sha256"]
        if bound[0].get("model_sha256") != model_sha:
            raise PermissionError("configured group router artifact binding differs")

        def current() -> None:
            registry = load_provider_registry(engine_root)
            matches = [item for item in registry["adapters"] if item["adapter_id"] == row["adapter_id"]]
            if len(matches) != 1 or matches[0].get("admitted") is not True or matches[0].get("status") != "ready":
                raise PermissionError("configured group provider adapter is not admitted and ready")
            state = runtime.status(session_id)
            if state["state"] != "running":
                raise PermissionError("configured group router is no longer running")
            custody = runtime.manager.ledger.get(str(state["resource_id"]))
            if not custody.active or type(custody.pid) is not int or custody.pid <= 0:
                raise PermissionError("configured group router lacks active native process custody")
            fingerprint = _process_start_fingerprint(custody.pid)
            if fingerprint is None or custody.process_identity != "process-start:" + fingerprint:
                raise PermissionError("configured group router process-start identity is not current")
            current_boot = _host_boot_generation()
            if not custody.host_boot_generation or not current_boot or custody.host_boot_generation != current_boot:
                raise PermissionError("configured group router belongs to another boot generation")
            current_profiles = [item for item in load_runtime_profiles(engine_root)
                                if item.profile_id == row["profile_id"]]
            if len(current_profiles) != 1 or current_profiles[0].profile_sha256 != profile.profile_sha256:
                raise PermissionError("configured group model/profile/session changed after resolution")

        current()
        adapter = LlamaCppStreamingHttpAdapter(
            runtime._router_origin(session_id), adapter_id=row["adapter_id"],
            session_id=session_id, model_sha256=model_sha, wire_model_name=model_id,
        )
        return GroupProviderBinding(model_id, model_sha, profile, adapter, session_id,
                                    row["budget_id"], current)

    return resolve
