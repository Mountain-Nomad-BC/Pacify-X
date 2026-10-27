import json
from dataclasses import replace
from pathlib import Path

import pytest
from tests.test_remote_profile_catalog import profile_config


def attachment(profile_config):
    from runtime.remote_provider_profiles import ROOT
    from runtime.studio_models import EffectGrant
    from runtime.remote_model_attachment import build_remote_model_attachment
    root, authority, row, body, path = profile_config
    authority.admit_grant(EffectGrant(row['grant_id'], 'fixture-owner', ('read', 'write', 'network'),
        (ROOT, row['origin']), 'fixture-owner', ('controlled-fixture',), '2099-01-01T00:00:00Z', 'admitted'))
    return build_remote_model_attachment(root, profile_id=row['profile_id'], requester_id='fixture-owner')


def test_signed_profile_and_native_grant_bind_remote_service_identity(profile_config):
    from runtime.model_attachment import model_attachment_from_dict, validate_model_attachment
    from runtime.contracts import validate_instance
    value = attachment(profile_config)
    root, *_ = profile_config
    assert model_attachment_from_dict(value.as_dict()) == value
    assert value.model_id != value.provider_model_id
    assert value.authority_class == 'external_authority'
    assert validate_model_attachment(value, root=root)['valid']
    validate_instance(value.as_dict(), Path('contracts/model_attachment.schema.json'))


def test_remote_attachment_cannot_impersonate_local_weights_or_change_service(profile_config):
    from runtime.model_attachment import validate_model_attachment
    value = attachment(profile_config)
    for changes in [{'privacy': 'local'}, {'authority_class': 'contained'}, {'provider_model_id': 'other'},
                    {'approved_addresses': ('127.0.0.1',)}, {'grant_revision': '0' * 64}]:
        assert not validate_model_attachment(replace(value, **changes))['valid']


def test_prepared_attachment_is_invalid_after_current_signed_profile_changes(profile_config):
    from runtime.model_attachment import validate_model_attachment
    value = attachment(profile_config)
    root, authority, row, body, path = profile_config
    row['model_revision'] = 'fixture-new-revision'
    path.write_text(json.dumps(authority.sign_receipt(body)), encoding='utf-8')
    assert not validate_model_attachment(value, root=root)['valid']


def test_uncommissioned_profile_has_no_attachment_authority(profile_config):
    from runtime.remote_model_attachment import build_remote_model_attachment
    root, _, row, _, _ = profile_config
    with pytest.raises((PermissionError, ValueError)):
        build_remote_model_attachment(root, profile_id=row['profile_id'], requester_id='fixture-owner')
