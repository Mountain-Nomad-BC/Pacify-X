"""Exact remote service identity; never a declaration of model weights custody."""
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import re

from .remote_provider_profiles import load_profiles, digest, https_origin, ROOT

SCHEMA = 'px.remote-model-attachment/2.0'


@dataclass(frozen=True, slots=True)
class RemoteModelAttachment:
    schema_version: str
    attachment_id: str
    model_id: str
    provider_model_id: str
    model_revision: str
    provider_id: str
    adapter_id: str
    profile_id: str
    profile_sha256: str
    origin: str
    approved_addresses: tuple[str, ...]
    context_tokens: int
    max_output_tokens: int
    privacy: str
    authority_class: str
    requester_id: str
    grant_id: str
    grant_revision: str
    policy_locator: str
    budget_id: str
    revision_evidence_sha256: str
    attachment_sha256: str

    def as_dict(self):
        value = asdict(self)
        value['approved_addresses'] = list(self.approved_addresses)
        return value


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def remote_branch_id(provider_id, profile_id):
    """Qualify a branch by service/profile without altering the vendor wire name."""
    if any(type(value) is not str or not value or len(value.encode()) > 512 or
           any(ord(character) < 32 for character in value) for value in (provider_id, profile_id)):
        raise ValueError('bounded remote service/profile identity required')
    return 'remote-model-' + _hash({'provider_id': provider_id, 'profile_id': profile_id})


def remote_model_attachment_from_dict(value):
    if type(value) is not dict or set(value) != set(RemoteModelAttachment.__dataclass_fields__):
        raise ValueError('closed remote service attachment required')
    if type(value['approved_addresses']) is not list:
        raise ValueError('remote address list required')
    attachment = RemoteModelAttachment(**{**value, 'approved_addresses': tuple(value['approved_addresses'])})
    report = validate_remote_model_attachment(attachment)
    if not report['valid']:
        raise ValueError('; '.join(report['errors']))
    return attachment


def _from_profile(profile, requester_id, grant_revision):
    body = {key: profile[key] for key in ('model_id', 'model_revision', 'provider_id', 'adapter_id', 'profile_id',
            'origin', 'approved_addresses', 'context_tokens', 'max_output_tokens', 'grant_id',
            'policy_locator', 'budget_id')}
    body['provider_model_id'] = body.pop('model_id')
    body['model_id'] = remote_branch_id(profile['provider_id'], profile['profile_id'])
    body.update(schema_version=SCHEMA, profile_sha256=digest(profile), requester_id=requester_id,
                grant_revision=grant_revision, privacy='policy_gated', authority_class='external_authority',
                revision_evidence_sha256=digest(profile['revision_evidence']))
    body['attachment_id'] = 'remote-model-attachment-' + _hash(body)[:24]
    body['attachment_sha256'] = _hash(body)
    return remote_model_attachment_from_dict(body)


def build_remote_model_attachment(root, *, profile_id, requester_id):
    authority, profiles = load_profiles(root)
    matches = [row for row in profiles if row['profile_id'] == profile_id]
    if authority is None or len(matches) != 1 or requester_id not in matches[0]['authorized_requesters']:
        raise PermissionError('exact approved remote profile/requester required')
    profile = matches[0]
    grant, revision = authority.resolve_grant(profile['grant_id'], subject_id=requester_id,
                                               required_effects=('read', 'write', 'network'))
    required = {profile['origin'], ROOT + '/gateway/events', ROOT + '/gateway/budget'}
    if any(not any(scope == allowed or scope.startswith(allowed.rstrip('/') + '/')
                   for allowed in grant['scope_roots']) for scope in required):
        raise PermissionError('remote grant lacks actual egress/budget/event custody')
    return _from_profile(profile, requester_id, revision)


def validate_remote_model_attachment(attachment, *, root=None, expected_attachment_sha256=None):
    errors = []
    try:
        if type(attachment) is not RemoteModelAttachment or type(attachment.approved_addresses) is not tuple:
            raise ValueError('native immutable remote attachment required')
        value = attachment.as_dict()
        from .remote_service_protocols import service_protocol
        protocol = service_protocol(value['adapter_id'], value['provider_id'])
        if value['schema_version'] != SCHEMA or (protocol['origin'] is not None and protocol['origin'] != value['origin']):
            raise ValueError('unsupported remote service identity')
        for key, item in value.items():
            if key not in {'approved_addresses', 'context_tokens', 'max_output_tokens'}:
                if type(item) is not str or not item or len(item.encode()) > 512 or any(ord(c) < 32 for c in item):
                    raise ValueError('bounded remote attachment text required')
        for key in ('profile_sha256', 'grant_revision', 'revision_evidence_sha256', 'attachment_sha256'):
            if re.fullmatch('[0-9a-f]{64}', value[key]) is None:
                raise ValueError('exact remote digest required')
        if attachment.privacy != 'policy_gated' or attachment.authority_class != 'external_authority':
            raise ValueError('remote privacy/authority cannot impersonate local custody')
        if attachment.model_id != remote_branch_id(attachment.provider_id, attachment.profile_id):
            raise ValueError('remote branch identity differs from exact service/profile')
        if attachment.model_revision.casefold() in {'latest', 'main', 'master', 'head', 'stable'} or attachment.model_revision.casefold().endswith(':latest'):
            raise ValueError('remote model revision must be exact')
        if any(type(value[key]) is not int or not 1 <= value[key] <= 10_000_000
               for key in ('context_tokens', 'max_output_tokens')) or attachment.max_output_tokens > attachment.context_tokens:
            raise ValueError('remote token bounds invalid')
        https_origin(attachment.origin, value['approved_addresses'])
        if not attachment.policy_locator.startswith(ROOT + '/') or '\\' in attachment.policy_locator or any(p in {'', '.', '..'} for p in attachment.policy_locator.split('/')):
            raise ValueError('remote policy locator outside native owner')
        unsigned = {k: v for k, v in value.items() if k != 'attachment_sha256'}
        if attachment.attachment_id != 'remote-model-attachment-' + _hash({k: v for k, v in unsigned.items() if k != 'attachment_id'})[:24] or attachment.attachment_sha256 != _hash(unsigned):
            raise ValueError('remote attachment content identity differs')
        if expected_attachment_sha256 is not None and attachment.attachment_sha256 != expected_attachment_sha256:
            raise ValueError('remote attachment differs from prepared plan')
        if root is not None and build_remote_model_attachment(root, profile_id=attachment.profile_id,
                requester_id=attachment.requester_id) != attachment:
            raise ValueError('remote attachment differs from current signed profile/grant')
    except (ValueError, TypeError, PermissionError, OSError) as error:
        errors.append(str(error))
    return {'schema_version': SCHEMA, 'valid': not errors, 'errors': errors,
            'attachment_sha256': getattr(attachment, 'attachment_sha256', None), 'authority_granted': False}
