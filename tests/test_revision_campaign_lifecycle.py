"""Real revision selection and WAL publication in disposable project roots."""
import hashlib
import json
from pathlib import Path

import pytest

from runtime import revision_campaign_lifecycle as lifecycle
from runtime.project_revision_succession import (
    ACTIVE_REVISION_PATH, SUCCESSION_STATE_PATH, STATE_SCHEMA,
    current_revision_root, _digest,
)
from runtime.release_signing import canonical_bytes
from runtime.test_profiles import close_repair_intake, freeze_repair_campaign, ProcessingOrderBlocked
from runtime.wal_transaction import JsonWal
from tests.test_project_revision_succession import (
    AUTHORIZATION, PREDECESSOR, PREDECESSOR_BYTES, PREDECESSOR_SHA, PROPOSAL,
    _activated_event, planned_event,
)

ADMISSION = 'gap-event:disposable-lifecycle-test'


@pytest.fixture
def project(tmp_path, monkeypatch):
    record = {'project_id': PREDECESSOR['project_id']}
    policy = {'campaign_id': PREDECESSOR['campaign_id']}
    parent = tmp_path / 'evidence/project-revision-succession' / PREDECESSOR['campaign_id'] / PREDECESSOR_SHA
    parent.mkdir(parents=True)
    for name, raw in [('repair-campaign.json', PREDECESSOR_BYTES),
                      ('project-record.json', canonical_bytes(record)),
                      ('validation-policy.json', canonical_bytes(policy))]:
        (parent / name).write_bytes(raw)
    proposal = {**PROPOSAL, 'predecessor_campaign_state_sha256': _digest(PREDECESSOR),
                'predecessor_project_record_sha256': hashlib.sha256(canonical_bytes(record)).hexdigest(),
                'predecessor_validation_policy_sha256': hashlib.sha256(canonical_bytes(policy)).hexdigest()}
    event = _activated_event(planned_event(proposal, {**AUTHORIZATION, **proposal}))
    revision = tmp_path / '.engineering-bootstrap/project-revisions' / PROPOSAL['successor_project_id']
    revision.mkdir(parents=True)
    campaign = {'schema_version': 'px.repair-campaign/1.0',
                'project_id': PROPOSAL['successor_project_id'],
                'campaign_id': PROPOSAL['successor_campaign_id'], 'phase': 'intake',
                'intake_open': True, 'unresolved': ['causal-finding'],
                'revision_parent_campaign_id': PREDECESSOR['campaign_id'],
                'revision_parent_sha256': PREDECESSOR_SHA,
                'succession_event_sha256': event['event_sha256']}
    validation = {'authority': 'OWNER-FRESH-VALIDATION-001', 'basis': 'current_implementation',
                  'campaign_id': campaign['campaign_id'], 'revision_succession': {
                      'event_sha256': event['event_sha256'],
                      'predecessor_campaign_id': PREDECESSOR['campaign_id'],
                      'predecessor_raw_sha256': PREDECESSOR_SHA,
                      'predecessor_project_record_sha256': proposal['predecessor_project_record_sha256'],
                      'predecessor_validation_policy_sha256': proposal['predecessor_validation_policy_sha256'],
                      'campaign_state_sha256': hashlib.sha256(canonical_bytes(campaign)).hexdigest()}}
    for name, value in [('repair-campaign.json', campaign), ('validation-policy.json', validation),
                        ('project-record.json', {'project_id': campaign['project_id']})]:
        (revision / name).write_bytes(canonical_bytes(value))
    state = tmp_path / SUCCESSION_STATE_PATH
    state.parent.mkdir(parents=True)
    state.write_bytes(canonical_bytes({'schema_version': STATE_SCHEMA, 'events': [event]}))
    pointer = {'schema_version': 'px.active-project-revision/1.0',
               'project_id': campaign['project_id'], 'revision_root': revision.relative_to(tmp_path).as_posix(),
               'event_sha256': event['event_sha256']}
    for name, key in [('repair-campaign.json', 'campaign_sha256'),
                      ('validation-policy.json', 'policy_sha256'),
                      ('project-record.json', 'project_record_sha256')]:
        pointer[key] = hashlib.sha256((revision / name).read_bytes()).hexdigest()
    target = tmp_path / ACTIVE_REVISION_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(canonical_bytes(pointer))
    assert current_revision_root(tmp_path) == revision
    # Isolated phase/publication test, not production authority issuance. Real
    # signed authorization/provenance is covered separately by succession tests.
    monkeypatch.setattr(lifecycle, '_guard_succession_effect', lambda *a: None)
    return tmp_path, revision, parent


def repair(project):
    root, revision, _ = project
    lifecycle.begin_repair(root, admission_event_id=ADMISSION)
    lifecycle.resolve_findings(root, admission_event_id=ADMISSION,
                               evidence_by_finding={'causal-finding': 'disposable-causal-test'})
    return root, revision


def receipt(root, revision):
    artifact = root / 'operational-result.txt'
    artifact.write_text('actual disposable operational result', encoding='utf-8')
    result = {'schema_version': 'px.operational-verification/1.0', 'valid': True,
              'campaign_id': json.loads((revision / 'repair-campaign.json').read_bytes())['campaign_id'],
              'campaign_state_sha256': hashlib.sha256((revision / 'repair-campaign.json').read_bytes()).hexdigest(),
              'unresolved_count': 0, 'checks': [{'name': 'disposable-operation', 'passed': True,
                  'exit_code': 0, 'artifact': artifact.name,
                  'artifact_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}]}
    (root / 'operational.json').write_text(json.dumps(result), encoding='utf-8')
    return 'operational.json'


def test_revision_closes_and_freezes_through_public_dispatch_without_touching_predecessor(project):
    root, revision, parent = project
    preserved = {p.name: p.read_bytes() for p in parent.iterdir()}
    repair(project)
    result = close_repair_intake(root, admission_event_id=ADMISSION, closure_authority='fixture-owner')
    assert result['phase'] == 'operational_verification'
    assert 'certify' in result['blocked_stages']
    result = freeze_repair_campaign(root, admission_event_id=ADMISSION, evidence_path=receipt(root, revision))
    assert result['phase'] == 'repair_frozen'
    assert current_revision_root(root) == revision
    assert {p.name: p.read_bytes() for p in parent.iterdir()} == preserved
    with pytest.raises(ProcessingOrderBlocked):
        close_repair_intake(root, admission_event_id=ADMISSION, closure_authority='fixture-owner')


def test_unresolved_intake_and_stale_operational_artifact_cannot_freeze(project):
    root, revision, _ = project
    lifecycle.begin_repair(root, admission_event_id=ADMISSION)
    before = (revision / 'repair-campaign.json').read_bytes()
    with pytest.raises(ProcessingOrderBlocked):
        close_repair_intake(root, admission_event_id=ADMISSION, closure_authority='fixture-owner')
    assert (revision / 'repair-campaign.json').read_bytes() == before
    lifecycle.resolve_findings(root, admission_event_id=ADMISSION, evidence_by_finding={'causal-finding': 'proof'})
    close_repair_intake(root, admission_event_id=ADMISSION, closure_authority='fixture-owner')
    evidence = receipt(root, revision)
    (root / 'operational-result.txt').write_text('tampered', encoding='utf-8')
    before = (revision / 'repair-campaign.json').read_bytes()
    with pytest.raises(ProcessingOrderBlocked, match='hash is stale'):
        freeze_repair_campaign(root, admission_event_id=ADMISSION, evidence_path=evidence)
    assert (revision / 'repair-campaign.json').read_bytes() == before


@pytest.mark.parametrize('index', [0, 1, 2])
def test_interrupted_revision_closure_recovers_all_three_bound_images(project, monkeypatch, index):
    root, revision = repair(project)
    original = JsonWal.commit
    def interrupted(self, artifacts, **kwargs):
        def fault(label):
            if label == f'target:{index}:published':
                raise RuntimeError('injected phase publication interruption')
        return original(self, artifacts, fault_injector=fault, **kwargs)
    monkeypatch.setattr(JsonWal, 'commit', interrupted)
    with pytest.raises(RuntimeError, match='injected phase'):
        close_repair_intake(root, admission_event_id=ADMISSION, closure_authority='fixture-owner')
    wal = JsonWal(Path('.engineering-bootstrap/project-revision-succession/wal'), root)
    assert wal._pending_transactions()
    wal.recover()
    assert current_revision_root(root) == revision
    assert lifecycle.status(root)['phase'] == 'operational_verification'


def test_admission_is_rechecked_immediately_before_publication(project, monkeypatch):
    root, revision = repair(project)
    before = (revision / 'repair-campaign.json').read_bytes()
    calls = []
    def guard(*args):
        calls.append(args)
        if len(calls) == 2:
            raise ValueError('admission expired while waiting')
    monkeypatch.setattr(lifecycle, '_guard_succession_effect', guard)
    with pytest.raises(ValueError, match='expired'):
        close_repair_intake(root, admission_event_id=ADMISSION, closure_authority='fixture-owner')
    assert (revision / 'repair-campaign.json').read_bytes() == before


@pytest.mark.parametrize('field', ['unresolved_count', 'exit_code'])
def test_boolean_cannot_impersonate_passing_integer_evidence(project, field):
    root, revision = repair(project)
    close_repair_intake(root, admission_event_id=ADMISSION, closure_authority='fixture-owner')
    evidence = receipt(root, revision)
    path = root / evidence
    value = json.loads(path.read_bytes())
    if field == 'unresolved_count':
        value[field] = False
    else:
        value['checks'][0][field] = False
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ProcessingOrderBlocked):
        freeze_repair_campaign(root, admission_event_id=ADMISSION, evidence_path=evidence)
    assert lifecycle.status(root)['phase'] == 'operational_verification'


def test_concurrent_revision_closure_has_one_winner(project):
    from concurrent.futures import ThreadPoolExecutor
    root, _ = repair(project)
    def attempt():
        try:
            close_repair_intake(root, admission_event_id=ADMISSION, closure_authority='fixture-owner')
            return 'passed'
        except ProcessingOrderBlocked:
            return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == ['passed', 'refused']


def test_policy_change_between_validation_and_publication_is_not_overwritten(project, monkeypatch):
    from runtime import test_profiles
    root, revision = repair(project)
    before = (revision / 'repair-campaign.json').read_bytes()
    prepare = test_profiles.prepare_intake_closure
    def tamper(*args, **kwargs):
        state = prepare(*args, **kwargs)
        (revision / 'validation-policy.json').write_text('{"concurrent":true}', encoding='utf-8')
        return state
    monkeypatch.setattr(test_profiles, 'prepare_intake_closure', tamper)
    with pytest.raises(lifecycle.RevisionCampaignBlocked, match='before-images changed'):
        close_repair_intake(root, admission_event_id=ADMISSION, closure_authority='fixture-owner')
    assert (revision / 'repair-campaign.json').read_bytes() == before
    assert (revision / 'validation-policy.json').read_text() == '{"concurrent":true}'
