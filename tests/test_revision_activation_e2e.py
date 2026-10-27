"""Real signed policy/authorization and WAL activation in isolated roots.

Only host work-admission and source classification are fixture seams. These
checks do not grant production authority or certify the installed product.
"""
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from runtime import project_revision_succession as succession
from runtime.release_signing import canonical_bytes, public_key_fingerprint
from runtime.trusted_evidence import sign_evidence_record
from tests.test_project_revision_succession import PREDECESSOR, PROPOSAL, AUTHORIZATION, SOURCE_SHA
from tests.test_trust_boundaries import _authority


def _signed_case(root, monkeypatch, *, legacy_missing_project_id=False):
    assert shutil.which('ssh-keygen'), 'mandatory signed activation test requires ssh-keygen'
    key, trust, identity, publisher = _authority(root / 'fixture-authority')
    old = dict(PREDECESSOR)
    if legacy_missing_project_id:
        old.pop('project_id')
    campaign = root / succession.PROJECT_CAMPAIGN_PATH
    campaign.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(old)
    campaign.write_bytes(raw)
    record = root / succession.PROJECT_RECORD_PATH
    record_raw = canonical_bytes({'project_id': PREDECESSOR['project_id'], 'name': 'fixture'})
    record.write_bytes(record_raw)
    predecessor_policy = root / 'policies/rev1xx-validation.json'
    predecessor_policy.parent.mkdir()
    predecessor_policy.write_bytes(canonical_bytes({'campaign_id': old['campaign_id'], 'basis': 'fixture predecessor'}))
    now = datetime.now(timezone.utc)
    policy = {'schema_version': succession.POLICY_SCHEMA, 'policy_id': 'fixture-succession-policy',
        'status': 'active', 'authorization_schema': succession.AUTH_SCHEMA,
        'trusted_authorities': [{'identity': 'fixture-successor-owner',
            'fingerprint': public_key_fingerprint(key.with_suffix('.pub')),
            'public_key': key.with_suffix('.pub').read_text(encoding='utf-8').strip(),
            'publisher': publisher, 'status': 'active'}],
        'revoked_authorizations': [], 'revision_scope': [PROPOSAL['successor_project_id']],
        'revocation_registry': {'schema_version': 'px.authorization-revocation-registry/1.0',
            'checked_at': now.isoformat(), 'revoked': [], 'superseded': {}}}
    store = root / 'fixture-evidence-store'
    store.mkdir()
    policy_path = store / 'owner-policy.json'
    policy_path.write_bytes(canonical_bytes(policy))
    trusted = json.loads(trust.read_text(encoding='utf-8'))
    trusted['trusted_signers'][0]['evidence_producers']['project-revision-succession-policy'] = ['provenance']
    trust.write_bytes(canonical_bytes(trusted))
    proof_path = store / 'activation-policy-proof.json'
    proof = sign_evidence_record({'schema_version': '1.0', 'evidence_id': 'activation-policy-proof',
        'evidence_type': 'provenance', 'producer': 'project-revision-succession-policy',
        'project_id': PREDECESSOR['project_id'], 'subject_id': policy['policy_id'],
        'created_at': now.isoformat(), 'artifact': {'path': policy_path.name,
            'sha256': hashlib.sha256(policy_path.read_bytes()).hexdigest()},
        'result': {'verified': True}}, private_key=key,
        signature_path=proof_path.with_suffix('.json.sig'), identity=identity, publisher=publisher)
    proof_path.write_bytes(canonical_bytes(proof))
    proposal = {**PROPOSAL, 'owner_policy_id': policy['policy_id'],
        'predecessor_raw_sha256': hashlib.sha256(raw).hexdigest(),
        'predecessor_project_record_sha256': hashlib.sha256(record_raw).hexdigest(),
        'predecessor_validation_policy_sha256': hashlib.sha256(predecessor_policy.read_bytes()).hexdigest()}
    auth = {**AUTHORIZATION, **proposal, 'issuer': 'fixture-successor-owner',
        'issued_at': (now - timedelta(minutes=1)).isoformat(),
        'expires_at': (now + timedelta(hours=1)).isoformat(),
        'validation_policy': {'schema_version': 'px.validation-basis/1.0',
            'campaign_id': PROPOSAL['successor_campaign_id'], 'authority': 'OWNER-FRESH-VALIDATION-001',
            'basis': 'current_implementation'}, 'replay_status': 'unused',
        'signature': {'algorithm': 'ssh-ed25519', 'namespace': succession.AUTH_NAMESPACE,
            'identity': 'fixture-successor-owner', 'fingerprint': public_key_fingerprint(key.with_suffix('.pub'))}}
    auth['content_sha256'] = hashlib.sha256(canonical_bytes({
        k: v for k, v in auth.items() if k not in {'signature', 'content_sha256'}})).hexdigest()
    auth_path = root / 'fixture-authorization.json'
    auth_path.write_bytes(canonical_bytes(auth))
    subprocess.run(['ssh-keygen', '-Y', 'sign', '-f', str(key), '-n', succession.AUTH_NAMESPACE,
        str(auth_path)], check=True, capture_output=True, timeout=30)
    monkeypatch.setattr(succession, '_guard_succession_effect', lambda *args: None)
    monkeypatch.setattr(succession, 'current_source_digest', lambda root: SOURCE_SHA)
    return {'predecessor_campaign': old, 'predecessor_raw_sha256': proposal['predecessor_raw_sha256'],
        'proposal': proposal, 'owner_authorization': auth, 'policy_path': policy_path,
        'signature_path': auth_path.with_suffix('.json.sig'),
        'policy_evidence_reference': 'evidence:activation-policy-proof', 'evidence_store': store,
        'evidence_trust_policy_path': trust, 'project_id': PREDECESSOR['project_id'],
        'admission_event_id': 'gap-event:isolated-activation-fixture'}, campaign, raw, record, record_raw


@pytest.mark.parametrize('legacy_missing_project_id', [False, True])
def test_real_signed_activation_preserves_predecessor_and_selects_fresh_intake(tmp_path, monkeypatch, legacy_missing_project_id):
    args, campaign, raw, record, record_raw = _signed_case(tmp_path, monkeypatch,
        legacy_missing_project_id=legacy_missing_project_id)
    result = succession.SuccessionLedger(tmp_path).activate_revision(**args)
    assert result['activated'] is True
    assert campaign.read_bytes() == raw
    assert record.read_bytes() == record_raw
    selected = succession.current_revision_root(tmp_path)
    state = json.loads((selected / 'repair-campaign.json').read_text(encoding='utf-8'))
    assert state['phase'] == 'intake' and state['intake_open'] is True
    assert state['unresolved'] == AUTHORIZATION['intake_findings']
    assert not (selected / 'release-identity.json').exists()
    archive = tmp_path / 'evidence/project-revision-succession' / PREDECESSOR['campaign_id'] / hashlib.sha256(raw).hexdigest()
    assert (archive / 'repair-campaign.json').read_bytes() == raw
    assert (archive / 'project-record.json').read_bytes() == record_raw
