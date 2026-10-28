import json
import pytest
from tests.test_remote_profile_catalog import profile_config
from tests.test_remote_attachment_identity import attachment
from tests.test_provider_gateway_streaming import _project
from runtime.group_provider_adapters import build_group_adapter_resolver, RemoteGroupProviderBinding


def binding(profile_config, tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("binding resolution attempted a network connection"))
    root, authority, row, _, _ = profile_config
    attached = attachment(profile_config)
    engine = _project(str(tmp_path))
    registry_path = engine / "registry/provider_adapter_registry.json"
    # Use the native registry owner filename used by the gateway fixture.
    from runtime.provider_gateway import REGISTRY_PATH
    registry_path = engine / REGISTRY_PATH
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["adapters"][0].update(adapter_id=attached.adapter_id, provider_id=attached.provider_id, mode="remote")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    policy = {"model": {"attachment_sha256": attached.attachment_sha256, "model_id": attached.provider_model_id, "model_revision": attached.model_revision, "provider_id": attached.provider_id, "adapter_id": attached.adapter_id, "privacy": attached.privacy, "authority_class": attached.authority_class}, "authority": {"revision": attached.grant_revision}, "egress": {"mode": "allowlist", "allowed_destinations": [attached.origin]}, "cost": {"budget_id": attached.budget_id}}
    path = root / attached.policy_locator
    path.write_text(json.dumps(authority.sign_receipt(policy)), encoding="utf-8")
    config = {"schema_version": "px.group-provider-adapters/1.0", "adapters": {attached.model_id: {"kind": "remote_provider", "profile_id": attached.profile_id, "adapter_id": attached.adapter_id, "budget_id": attached.budget_id, "requester_id": attached.requester_id, "attachment_sha256": attached.attachment_sha256}}}
    resolver = build_group_adapter_resolver(engine, root, config)
    return resolver, attached, authority, policy, path, registry, registry_path


def test_remote_binding_uses_current_native_signed_service_without_network(profile_config, tmp_path, monkeypatch):
    resolver, attached, *_ = binding(profile_config, tmp_path, monkeypatch)
    value = resolver(attached.model_id)
    assert type(value) is RemoteGroupProviderBinding
    value.assert_current()
    assert value.attachment == attached
    assert resolver("not-declared") is None


@pytest.mark.parametrize("mutation", ["policy", "registry"])
def test_binding_rechecks_authority_before_provider_work(profile_config, tmp_path, monkeypatch, mutation):
    resolver, attached, authority, policy, path, registry, registry_path = binding(profile_config, tmp_path, monkeypatch)
    value = resolver(attached.model_id)
    if mutation == "policy":
        policy["model"]["model_revision"] = "changed"
        path.write_text(json.dumps(authority.sign_receipt(policy)), encoding="utf-8")
    else:
        registry["adapters"][0]["admitted"] = False
        registry["adapters"][0]["status"] = "unconfigured"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(PermissionError):
        value.assert_current()
