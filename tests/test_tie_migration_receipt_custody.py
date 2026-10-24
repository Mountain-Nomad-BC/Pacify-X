import hashlib
import json
from pathlib import Path
import pytest
import runtime.tie_experience as owner
import runtime.usage_memory as memory_owner
from runtime.effect_intent import EffectIntentLedger
from runtime.scope_lease import ScopeLeaseStore
from runtime.resource_lifecycle import ResourceManager
from runtime.studio_models import AgentSpec, write_versioned_record


def objects(root, count=1):
    for identity in ('source-agent', 'destination-agent'):
        spec = AgentSpec(agent_id=identity, version='1.0.0', project_id='project-1', owner='fixture-owner',
            harness_id='harness-1', instruction_sha256='a'*64, capability_binding_ids=(),
            effect_grant_ids=(), required_tests=('tests/test_tie_migration_receipt_custody.py',))
        write_versioned_record(root, 'agent', identity, '1.0.0', spec)
    for index in range(count):
        memory_owner.record_studio_observation(root, 'agent', 'source-agent', '1.0.0',
            {'outcome': 'success', 'run_id': f'run-{index}', 'effect_id': f'effect-{index}'})
    return root / '.agentic_engineering_os_px/runtime-core/tie-migrations/receipts/migration.json'


def migrate(root, target):
    return owner.migrate(root, 'agent', 'source-agent', '1.0.0', new_identity='destination-agent',
                         new_version='1.0.0', receipt_path=target)


def destination_log(root):
    return memory_owner._studio_memory(root, 'agent', 'destination-agent', '1.0.0') / 'usage.jsonl'


def receipts(root):
    return [row for row in EffectIntentLedger(root)._load()['intents']
            if row['idempotency_key'].startswith('tie-migration-receipt-')]


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def test_actual_native_destination_commitments_and_receipt_publication(tmp_path):
    target = objects(tmp_path)
    result = migrate(tmp_path, target)
    retained = target.read_bytes()
    row = EffectIntentLedger(tmp_path).fence(result['receipt_effect_key'])
    assert row['disposition'] == 'committed'
    assert row['scopes'] == [target.relative_to(tmp_path).as_posix()]
    assert row['result_sha256'] == hashlib.sha256(retained).hexdigest()
    assert result['status'] == 'MIGRATED' and result['authority_granted'] is False
    commitment = result['destination_commitments'][0]
    assert EffectIntentLedger(tmp_path).fence(commitment['effect_intent_key'])['disposition'] == 'committed'
    resources = ResourceManager(tmp_path / '.agentic_engineering_os_px/resource-lifecycle/resources.json').ledger.observe()
    assert resources and all(not Path(r.path).exists() for r in resources)
    assert ScopeLeaseStore(tmp_path).active(effect='write') == ()


def test_committed_receipt_replay_is_observational_preserving_first_counter(tmp_path):
    target = objects(tmp_path)
    first = migrate(tmp_path, target)
    before = hashes(tmp_path)
    replay = migrate(tmp_path, target)
    assert replay['receipt_replayed'] is True and replay['already_migrated'] == 1
    assert json.loads(target.read_text(encoding='utf-8'))['already_migrated'] == first['already_migrated'] == 0
    assert replay['retained_receipt_sha256'] == first['retained_receipt_sha256']
    assert hashes(tmp_path) == before


@pytest.mark.parametrize('relative', ['runtime/authored.json', 'registry/foreign.json',
    '.px/skills/foreign/memory/receipt.json', '.agentic_engineering_os_px/runtime-core/other-owner/receipt.json'])
def test_foreign_target_refuses_before_any_destination_observation(tmp_path, relative):
    objects(tmp_path)
    before = hashes(tmp_path)
    with pytest.raises(ValueError, match='canonical PX-owned'):
        migrate(tmp_path, tmp_path / relative)
    assert not destination_log(tmp_path).exists()
    assert hashes(tmp_path) == before


def test_unfenced_existing_receipt_is_preserved_without_destination_effect(tmp_path):
    target = objects(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b'{"legacy":"preserve unfenced image"}\n')
    before = hashes(tmp_path)
    with pytest.raises(ValueError, match='collision'): migrate(tmp_path, target)
    assert hashes(tmp_path) == before
    assert not destination_log(tmp_path).exists()


def test_partial_receipt_proves_only_actual_committed_destination_rows(tmp_path, monkeypatch):
    target = objects(tmp_path, count=2)
    native = owner.record_studio_observation
    def fail_second(root, kind, identity, version, observation):
        if observation['run_id'] == 'run-1': raise ValueError('controlled destination refusal')
        return native(root, kind, identity, version, observation)
    monkeypatch.setattr(owner, 'record_studio_observation', fail_second)
    result = migrate(tmp_path, target)
    assert result['status'] == 'PARTIAL_MIGRATION'
    assert result['records_migrated'] == 1 and result['records_total'] == 2
    assert len(result['failures']) == 1 and len(result['destination_commitments']) == 1
    assert receipts(tmp_path)[0]['state'] == 'committed'
    assert len(destination_log(tmp_path).read_bytes().splitlines()) == 1


def test_publication_commit_failure_blocks_replay_before_new_copy(tmp_path, monkeypatch):
    target = objects(tmp_path)
    native = EffectIntentLedger.commit
    def fail_receipt(self, **kwargs):
        if kwargs['idempotency_key'].startswith('tie-migration-receipt-'):
            raise RuntimeError('controlled receipt settlement failure')
        return native(self, **kwargs)
    monkeypatch.setattr(EffectIntentLedger, 'commit', fail_receipt)
    with pytest.raises(RuntimeError): migrate(tmp_path, target)
    assert target.exists() and receipts(tmp_path)[0]['state'] == 'in_flight'
    before = hashes(tmp_path)
    with pytest.raises(ValueError, match='remains uncertain'): migrate(tmp_path, target)
    assert hashes(tmp_path) == before


def test_published_corrupt_image_does_not_settle_or_retry(tmp_path, monkeypatch):
    target = objects(tmp_path)
    native = owner.os.link
    def corrupt(source, destination, *args, **kwargs):
        result = native(source, destination, *args, **kwargs)
        if Path(destination) == target: target.write_bytes(b'corrupt retained receipt')
        return result
    monkeypatch.setattr(owner.os, 'link', corrupt)
    with pytest.raises(ValueError, match='retained receipt image'): migrate(tmp_path, target)
    assert receipts(tmp_path)[0]['state'] == 'in_flight'
    with pytest.raises(ValueError, match='remains uncertain'): migrate(tmp_path, target)


def test_real_source_drift_after_copy_cannot_claim_current_source_retention(tmp_path, monkeypatch):
    target = objects(tmp_path)
    native = owner.record_studio_observation
    def change_source(*args, **kwargs):
        result = native(*args, **kwargs)
        memory_owner.record_studio_observation(tmp_path, 'agent', 'source-agent', '1.0.0',
            {'outcome': 'failure', 'run_id': 'later-run', 'effect_id': 'later-effect'})
        return result
    monkeypatch.setattr(owner, 'record_studio_observation', change_source)
    with pytest.raises(ValueError, match='captured source image changed'): migrate(tmp_path, target)
    assert not target.exists()
    assert receipts(tmp_path) == []
    assert len(destination_log(tmp_path).read_bytes().splitlines()) == 1


def test_changed_captured_source_cannot_overwrite_previous_receipt(tmp_path):
    target = objects(tmp_path)
    migrate(tmp_path, target)
    retained = target.read_bytes()
    memory_owner.record_studio_observation(tmp_path, 'agent', 'source-agent', '1.0.0',
        {'outcome': 'success', 'run_id': 'later-run', 'effect_id': 'later-effect'})
    with pytest.raises(ValueError, match='collision'): migrate(tmp_path, target)
    assert target.read_bytes() == retained
    assert len(destination_log(tmp_path).read_bytes().splitlines()) == 1


def test_link_error_after_actual_publication_stays_uncertain(tmp_path, monkeypatch):
    target = objects(tmp_path)
    native = owner.os.link
    def fail_after_link(source, destination, *args, **kwargs):
        native(source, destination, *args, **kwargs)
        raise OSError('controlled error after actual exclusive publication')
    monkeypatch.setattr(owner.os, 'link', fail_after_link)
    with pytest.raises(OSError, match='after actual'): migrate(tmp_path, target)
    assert target.is_file()
    assert receipts(tmp_path)[0]['state'] == 'in_flight'
    with pytest.raises(ValueError, match='remains uncertain'): migrate(tmp_path, target)


def test_changed_destination_image_after_publication_cannot_settle(tmp_path, monkeypatch):
    target = objects(tmp_path)
    native = owner.os.link
    def append_after_link(source, destination, *args, **kwargs):
        result = native(source, destination, *args, **kwargs)
        memory_owner.record_studio_observation(tmp_path, 'agent', 'destination-agent', '1.0.0',
            {'outcome': 'failure', 'run_id': 'later-run', 'effect_id': 'later-effect'})
        return result
    monkeypatch.setattr(owner.os, 'link', append_after_link)
    with pytest.raises(ValueError, match='drifted before settlement'): migrate(tmp_path, target)
    assert target.is_file() and receipts(tmp_path)[0]['state'] == 'in_flight'


def test_unclosed_receipt_lease_blocks_committed_replay(tmp_path, monkeypatch):
    target = objects(tmp_path)
    native = ScopeLeaseStore.release
    def fail_receipt(self, **kwargs):
        if kwargs['execution_id'].startswith('tie-receipt-'):
            raise OSError('controlled receipt lease closure failure')
        return native(self, **kwargs)
    monkeypatch.setattr(ScopeLeaseStore, 'release', fail_receipt)
    with pytest.raises(ValueError, match='closure remains uncertain'): migrate(tmp_path, target)
    assert receipts(tmp_path)[0]['state'] == 'committed'
    before = hashes(tmp_path)
    with pytest.raises(ValueError, match='lease closure remains uncertain'): migrate(tmp_path, target)
    assert hashes(tmp_path) == before


def test_real_native_quarantine_stops_publication_before_target_effect(tmp_path, monkeypatch):
    target = objects(tmp_path)
    native = ResourceManager.create_workspace
    def quarantine_receipt(self, *args, **kwargs):
        result = native(self, *args, **kwargs)
        if kwargs['creator'] == 'runtime.tie_experience':
            leases = ScopeLeaseStore(tmp_path)
            lease = next(row for row in leases.active(effect='write')
                         if row.execution_id.startswith('tie-receipt-'))
            intent = next(row for row in receipts(tmp_path) if row['execution_id'] == lease.execution_id)
            leases.quarantine_unresolved(lease_id=lease.lease_id, execution_id=lease.execution_id,
                run_id=lease.execution_id, node_id='migration-receipt-publication',
                authority_reference_sha256=owner._sha(intent),
                attempt=1)
        return result
    monkeypatch.setattr(ResourceManager, 'create_workspace', quarantine_receipt)
    with pytest.raises(ValueError, match='lease is quarantined'): migrate(tmp_path, target)
    assert not target.exists()
    assert receipts(tmp_path)[0]['state'] == 'failed'
    assert ScopeLeaseStore(tmp_path).quarantines(effect='write')


def test_old_unfenced_destination_is_not_adopted_as_current_commitment(tmp_path):
    target = objects(tmp_path)
    source = memory_owner.retrieve_studio_experience(tmp_path, 'agent', 'source-agent', '1.0.0')
    original = source['records'][0]
    old = {k: v for k, v in original.items() if k not in {'tie_effect_key', 'tie_observation_sha256'}}
    old.update(subject_id='destination-agent', migrated_from='agent:source-agent@1.0.0',
        source_log_sha256=source['experience_log_sha256'], source_record_sha256=owner._sha(original))
    log = destination_log(tmp_path)
    log.parent.mkdir(parents=True)
    preserved = owner._canonical(old) + b'\n'
    log.write_bytes(preserved)
    result = migrate(tmp_path, target)
    assert result['status'] == 'PARTIAL_MIGRATION'
    assert result['records_migrated'] == 0 and result['destination_commitments'] == []
    assert 'no native commitment' in result['failures'][0]['reason']
    assert log.read_bytes() == preserved
    assert receipts(tmp_path)[0]['state'] == 'committed'
