import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest
import runtime.usage_memory as owner
from runtime.effect_intent import EffectIntentLedger
from runtime.scope_lease import ScopeLeaseStore, ScopeLeaseError
from runtime.resource_lifecycle import ResourceManager


def observation():
    return {'outcome': 'success', 'run_id': 'run-1', 'effect_id': 'effect-1', 'execution_id': 'execution-1'}


def memory(root):
    return root / '.px/skills/subject/memory'


def capture(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def record(root, value=None):
    return owner.record_observation(root, 'skill', 'subject', observation() if value is None else value)


def intents(root):
    return EffectIntentLedger(root)._load()['intents']


def test_normal_observation_has_actual_native_commit_and_ephemeral_closure(tmp_path):
    result = record(tmp_path)
    row = EffectIntentLedger(tmp_path).fence(result['recorded']['tie_effect_key'])
    assert row['disposition'] == 'committed'
    assert row['result_sha256'] == owner._sha(result['recorded'])
    assert row['scopes'] == ['.px/skills/subject/memory']
    assert ScopeLeaseStore(tmp_path).active(effect='write') == ()
    resources = ResourceManager(tmp_path / '.agentic_engineering_os_px/resource-lifecycle/resources.json').ledger.observe()
    assert resources
    assert all(not Path(r.path).exists() for r in resources)
    assert list((tmp_path / '.agentic_engineering_os_px/resource-lifecycle/cleanup-receipts').glob('*.json'))


def test_terminal_identity_replay_is_observational_and_does_not_append(tmp_path):
    first = record(tmp_path)
    before = capture(tmp_path)
    second = record(tmp_path)
    assert second['duplicate'] is True
    assert second['recorded'] == first['recorded']
    assert capture(tmp_path) == before
    assert second['stats']['record_count'] == 1


def test_conflicting_content_under_same_terminal_identity_refuses(tmp_path):
    record(tmp_path)
    before = capture(tmp_path)
    with pytest.raises(ValueError, match='identity/content'):
        record(tmp_path, {**observation(), 'notes': 'different evidence'})
    assert capture(tmp_path) == before


def test_failed_rollup_after_append_remains_uncertain_and_never_reappends(tmp_path, monkeypatch):
    def fail(*args, **kwargs): raise RuntimeError('controlled rollup failure')
    monkeypatch.setattr(owner, '_rebuild_stats_at', fail)
    with pytest.raises(RuntimeError): record(tmp_path)
    retained = (memory(tmp_path) / 'usage.jsonl').read_bytes()
    assert len(retained.splitlines()) == 1
    assert intents(tmp_path)[0]['state'] == 'in_flight'
    with pytest.raises(ValueError, match='reconciliation'): record(tmp_path)
    with pytest.raises(ValueError, match='custody remains uncertain'):
        owner.read_stats(tmp_path, 'skill', 'subject')
    assert (memory(tmp_path) / 'usage.jsonl').read_bytes() == retained
    assert ScopeLeaseStore(tmp_path).active(effect='write') == ()


def test_corrupt_promoted_rollup_is_not_committed(tmp_path, monkeypatch):
    native = owner.os.replace
    def corrupt(source, target):
        result = native(source, target)
        if Path(target) == memory(tmp_path) / 'stats.json': Path(target).write_bytes(b'{}')
        return result
    monkeypatch.setattr(owner.os, 'replace', corrupt)
    with pytest.raises(ValueError, match='promoted rollup image'): record(tmp_path)
    assert intents(tmp_path)[0]['state'] == 'in_flight'


def test_final_commit_failure_retains_actual_images_and_uncertain_intent(tmp_path, monkeypatch):
    def fail(self, **kwargs): raise RuntimeError('controlled final settlement failure')
    monkeypatch.setattr(EffectIntentLedger, 'commit', fail)
    with pytest.raises(RuntimeError): record(tmp_path)
    assert (memory(tmp_path) / 'usage.jsonl').is_file()
    assert (memory(tmp_path) / 'stats.json').is_file()
    assert intents(tmp_path)[0]['state'] == 'in_flight'
    with pytest.raises(ValueError, match='custody remains uncertain'):
        owner.read_stats(tmp_path, 'skill', 'subject')


def test_competing_native_lease_refuses_before_object_mutation(tmp_path):
    leases = ScopeLeaseStore(tmp_path)
    leases.acquire(lease_id='other-lease', execution_id='other-owner', effect='write',
        scopes=['.px/skills/subject/memory'], reason='competing native owner',
        expires_utc=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
    with pytest.raises(ScopeLeaseError): record(tmp_path)
    assert not memory(tmp_path).exists()
    assert intents(tmp_path) == []
    assert len(leases.active(effect='write')) == 1


def test_explicit_rollup_reconciliation_preserves_old_unfenced_log(tmp_path):
    directory = memory(tmp_path)
    directory.mkdir(parents=True)
    old = b'{"subject_kind":"skill","subject_id":"subject","outcome":"failure"}\n'
    (directory / 'usage.jsonl').write_bytes(old)
    result = owner.rebuild_stats(tmp_path, 'skill', 'subject')
    assert result['outcomes']['failure'] == 1
    assert (directory / 'usage.jsonl').read_bytes() == old
    assert intents(tmp_path)[0]['state'] == 'committed'
    assert intents(tmp_path)[0]['idempotency_key'].startswith('tie-rollup-')


def test_subject_initialization_is_native_fenced_without_fabricated_use(tmp_path):
    (tmp_path / '.px/skills/subject').mkdir(parents=True)
    result = owner.ensure_subject_memory(tmp_path, 'skill', 'subject')
    assert (memory(tmp_path) / 'usage.jsonl').read_bytes() == b''
    assert result['record_count'] == 0
    assert intents(tmp_path)[0]['state'] == 'committed'


def test_real_studio_terminal_consumer_keeps_persistence_failure_separate(tmp_path, monkeypatch):
    from runtime.studio_models import AgentSpec, write_versioned_record
    spec = AgentSpec(agent_id='agent-1', version='1.0.0', project_id='project-1', owner='fixture-owner',
        harness_id='harness-1', instruction_sha256='a'*64, capability_binding_ids=(),
        effect_grant_ids=(), required_tests=('tests/test_usage_memory_custody.py',))
    write_versioned_record(tmp_path, 'agent', spec.agent_id, spec.version, spec)
    def fail(*args, **kwargs): raise RuntimeError('controlled derived rollup failure')
    monkeypatch.setattr(owner, '_rebuild_stats_at', fail)
    result = owner.retain_studio_run_experience(tmp_path, 'agent', spec.agent_id, spec.version,
        run_id='run-1', state='succeeded', evidence_ref='unit-fixture/terminal-receipt.json', effect_id='effect-1')
    assert result['status'] == 'PERSISTENCE_FAILED'
    assert result['recorded'] is False
    assert result['authority_granted'] is False
    assert intents(tmp_path)[0]['state'] == 'in_flight'


def test_native_migration_retains_provenance_and_uses_destination_custody(tmp_path):
    from runtime.studio_models import AgentSpec, write_versioned_record
    from runtime.tie_experience import migrate
    for identity in ('source-agent', 'destination-agent'):
        spec = AgentSpec(agent_id=identity, version='1.0.0', project_id='project-1', owner='fixture-owner',
            harness_id='harness-1', instruction_sha256='a'*64, capability_binding_ids=(),
            effect_grant_ids=(), required_tests=('tests/test_usage_memory_custody.py',))
        write_versioned_record(tmp_path, 'agent', spec.agent_id, spec.version, spec)
    source = owner.record_studio_observation(tmp_path, 'agent', 'source-agent', '1.0.0', observation())
    source_memory = owner._studio_memory(tmp_path, 'agent', 'source-agent', '1.0.0')
    before = (source_memory / 'usage.jsonl').read_bytes()
    receipt = tmp_path / '.agentic_engineering_os_px/runtime-core/tie-migrations/receipts/unit-migration.json'
    result = migrate(tmp_path, 'agent', 'source-agent', '1.0.0', new_identity='destination-agent',
                     new_version='1.0.0', receipt_path=receipt)
    assert result['status'] == 'MIGRATED'
    destination = owner.retrieve_studio_experience(tmp_path, 'agent', 'destination-agent', '1.0.0')['records'][0]
    assert destination['tie_effect_key'] != source['recorded']['tie_effect_key']
    assert destination['source_record_sha256'] == owner._sha(source['recorded'])
    fence = EffectIntentLedger(tmp_path).fence(destination['tie_effect_key'])
    assert fence['disposition'] == 'committed'
    assert fence['scopes'] == [owner._studio_memory(tmp_path, 'agent', 'destination-agent', '1.0.0').relative_to(tmp_path).as_posix()]
    assert (source_memory / 'usage.jsonl').read_bytes() == before
    destination_log = owner._studio_memory(tmp_path, 'agent', 'destination-agent', '1.0.0') / 'usage.jsonl'
    retained = destination_log.read_bytes()
    repeated = migrate(tmp_path, 'agent', 'source-agent', '1.0.0', new_identity='destination-agent',
                     new_version='1.0.0', receipt_path=receipt)
    assert repeated['already_migrated'] == 1
    assert destination_log.read_bytes() == retained


def test_ephemeral_cleanup_error_does_not_falsely_commit_observation(tmp_path, monkeypatch):
    native = ResourceManager.reclaim_ephemeral_path
    def fail_after_cleanup(self, *args, **kwargs):
        native(self, *args, **kwargs)
        raise RuntimeError('controlled cleanup acknowledgement failure')
    monkeypatch.setattr(ResourceManager, 'reclaim_ephemeral_path', fail_after_cleanup)
    with pytest.raises(RuntimeError, match='cleanup acknowledgement'): record(tmp_path)
    assert intents(tmp_path)[0]['state'] == 'in_flight'
    assert ScopeLeaseStore(tmp_path).active(effect='write') == ()
    resources = ResourceManager(tmp_path / '.agentic_engineering_os_px/resource-lifecycle/resources.json').ledger.observe()
    assert resources and all(not Path(row.path).exists() for row in resources)


def test_lost_native_lease_before_rollup_refuses_and_retains_uncertainty(tmp_path, monkeypatch):
    native = owner._rebuild_stats_at
    def lose_lease(root, *args, **kwargs):
        leases = ScopeLeaseStore(root)
        for lease in leases.active(effect='write'):
            leases.release(lease_id=lease.lease_id, execution_id=lease.execution_id)
        return native(root, *args, **kwargs)
    monkeypatch.setattr(owner, '_rebuild_stats_at', lose_lease)
    with pytest.raises(ValueError, match='no longer live'): record(tmp_path)
    assert (memory(tmp_path) / 'usage.jsonl').is_file()
    assert not (memory(tmp_path) / 'stats.json').exists()
    assert intents(tmp_path)[0]['state'] == 'in_flight'


def test_incomplete_retained_log_tail_is_not_merged_or_rewritten(tmp_path):
    directory = memory(tmp_path)
    directory.mkdir(parents=True)
    retained = b'{"partial":'
    (directory / 'usage.jsonl').write_bytes(retained)
    with pytest.raises(ValueError, match='incomplete tail'): record(tmp_path)
    assert (directory / 'usage.jsonl').read_bytes() == retained
    assert intents(tmp_path)[0]['state'] == 'failed'


def test_object_lock_release_error_does_not_mask_primary_failure(tmp_path, monkeypatch):
    native = owner.FileLock
    class ReleaseFailure(native):
        def __exit__(self, *args):
            super().__exit__(*args)
            raise OSError('controlled object-lock release acknowledgement error')
    monkeypatch.setattr(owner, 'FileLock', ReleaseFailure)
    def primary(*args, **kwargs): raise RuntimeError('primary rollup failure')
    monkeypatch.setattr(owner, '_rebuild_stats_at', primary)
    with pytest.raises(RuntimeError, match='primary rollup failure') as error:
        record(tmp_path)
    assert any('object lock release' in note for note in error.value.__notes__)
    assert intents(tmp_path)[0]['state'] == 'in_flight'


def test_committed_payload_does_not_hide_unclosed_native_lease_on_replay(tmp_path, monkeypatch):
    def fail_release(self, **kwargs): raise OSError('controlled lease closure failure')
    monkeypatch.setattr(ScopeLeaseStore, 'release', fail_release)
    with pytest.raises(OSError, match='lease closure'): record(tmp_path)
    assert intents(tmp_path)[0]['state'] == 'committed'
    assert ScopeLeaseStore(tmp_path)._load()
    retained = (memory(tmp_path) / 'usage.jsonl').read_bytes()
    with pytest.raises(ValueError, match='lease closure remains uncertain'):
        record(tmp_path)
    assert (memory(tmp_path) / 'usage.jsonl').read_bytes() == retained


def test_native_quarantine_blocks_host_rollup_even_before_lease_expiry(tmp_path, monkeypatch):
    native = owner._rebuild_stats_at
    def quarantine_host(root, *args, **kwargs):
        leases = ScopeLeaseStore(root)
        lease = next(row for row in leases.active(effect='write') if row.execution_id.startswith('tie-update-'))
        intent = next(row for row in intents(root) if row['execution_id'] == lease.execution_id)
        leases.quarantine_unresolved(lease_id=lease.lease_id, execution_id=lease.execution_id,
            run_id=lease.execution_id, node_id='tie-host-rollup', authority_reference_sha256=owner._sha(intent), attempt=1)
        return native(root, *args, **kwargs)
    monkeypatch.setattr(owner, '_rebuild_stats_at', quarantine_host)
    with pytest.raises(ValueError, match='host mutation lease is quarantined'): record(tmp_path)
    assert (memory(tmp_path) / 'usage.jsonl').is_file()
    assert not (memory(tmp_path) / 'stats.json').exists()
    assert intents(tmp_path)[0]['state'] == 'in_flight'
    assert ScopeLeaseStore(tmp_path).quarantines(effect='write')
