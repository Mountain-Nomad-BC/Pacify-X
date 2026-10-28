"""Custody regressions for the non-deleting rollout source overlay."""
import pytest

from scripts.rollout.compare_trees import compare, inventory
from scripts.rollout.integration_plan import apply_plan, digest, eligible


@pytest.mark.parametrize('path', [
    'providers/agency_agents/agents/design/memory/agency.design.x/usage.jsonl',
    'orchestration/workflows/x/memory/bindings.json',
    '.px/skills/x/memory/stats.json', '.env.local',
    'registry/operational_gap_ledger.head.json',
    '.agentic_engineering_os_px/project-record.json', 'evidence/releases/old/certificate.json',
])
def test_live_beta_state_is_not_source_overlay(path):
    assert not eligible(path)


def test_comparison_retains_incumbent_only_files(tmp_path):
    candidate, incumbent = tmp_path / 'candidate', tmp_path / 'incumbent'
    candidate.mkdir(); incumbent.mkdir()
    (candidate / 'a.py').write_text('new')
    (incumbent / 'a.py').write_text('old')
    (incumbent / 'user.txt').write_text('preserve')
    result = compare(inventory(candidate), inventory(incumbent))
    assert result['changed'] == ['a.py']
    assert result['incumbent_only'] == ['user.txt']
    assert (incumbent / 'user.txt').read_text() == 'preserve'


def test_overlay_checks_all_preimages_before_writing(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir(); target.mkdir(); (target / '.git').write_text('worktree marker')
    files = []
    (source / 'runtime').mkdir(); (target / 'runtime').mkdir()
    for name in ('runtime/a.py', 'runtime/b.py'):
        (source / name).write_text('new')
        (target / name).write_text('old')
        files.append(dict(path=name, before_sha256=digest(target / name),
                          after_sha256=digest(source / name),disposition="port",review_note="Reviewed disposable fixture"))
    (target / 'runtime/b.py').write_text('concurrent edit')
    with pytest.raises(ValueError, match='Concurrent change'):
        apply_plan(dict(candidate=str(source), target=str(target), files=files))
    assert (target / 'runtime/a.py').read_text() == 'old'
    assert (target / 'runtime/b.py').read_text() == 'concurrent edit'


def test_overlay_never_removes_target_only_data(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir(); target.mkdir(); (target / '.git').write_text('worktree marker')
    (source / 'runtime').mkdir();(target / 'runtime').mkdir()
    (source / 'runtime/a.py').write_text('new')
    (target / 'preserved.txt').write_text('user data')
    apply_plan(dict(candidate=str(source), target=str(target), files=[
        dict(path='runtime/a.py', before_sha256=None, after_sha256=digest(source / 'runtime/a.py'),disposition='port',review_note='Reviewed disposable fixture')]))
    assert (target / 'runtime/a.py').read_text() == 'new'
    assert (target / 'preserved.txt').read_text() == 'user data'




def plan_fixture(tmp_path):
    source,target=tmp_path/'source',tmp_path/'target'
    source.mkdir();target.mkdir();(target/'.git').write_text('worktree marker')
    (source/'runtime').mkdir();(target/'runtime').mkdir()
    (source/'runtime/a.py').write_text('reviewed new source')
    (target/'runtime/a.py').write_text('incumbent source')
    return source,target,dict(candidate=str(source),target=str(target),files=[dict(path='runtime/a.py',
        before_sha256=digest(target/'runtime/a.py'),after_sha256=digest(source/'runtime/a.py'),
        disposition='port',review_note='Reviewed disposable fixture')])


@pytest.mark.parametrize('name',['../escape.py','runtime/../escape.py','runtime\\escape.py','runtime/a.py:stream','.git','runtime/NUL.py','runtime/a.py.'])
def test_unsafe_port_paths_are_denied_before_source_effects(tmp_path,name):
    source,target,plan=plan_fixture(tmp_path);plan['files'][0]['path']=name
    with pytest.raises(ValueError):apply_plan(plan)
    assert (target/'runtime/a.py').read_text()=='incumbent source'


def test_unreviewed_or_duplicate_port_denominator_never_writes(tmp_path):
    source,target,plan=plan_fixture(tmp_path)
    plan['files'][0]['review_note']=''
    with pytest.raises(ValueError,match='review'):apply_plan(plan)
    plan['files'][0]['review_note']='Reviewed fixture';plan['files'].append(dict(plan['files'][0]))
    with pytest.raises(ValueError,match='Duplicate'):apply_plan(plan)
    assert (target/'runtime/a.py').read_text()=='incumbent source'


def test_source_and_destination_hardlinks_are_denied_with_external_canary_unchanged(tmp_path):
    import os
    source,target,plan=plan_fixture(tmp_path)
    canary=tmp_path/'canary';os.link(target/'runtime/a.py',canary)
    with pytest.raises(ValueError,match='single-link'):apply_plan(plan)
    assert canary.read_text()=='incumbent source'


def test_source_symlink_is_not_read_or_published(tmp_path):
    from runtime.secure_publish import read_physical_bytes
    source,target,plan=plan_fixture(tmp_path);canary=tmp_path/'canary';canary.write_text('external secret')
    leaf=source/'runtime/a.py';leaf.unlink()
    try:leaf.symlink_to(canary)
    except OSError as error:pytest.fail(f'Required hostile-link fixture unavailable: {error}')
    with pytest.raises((ValueError,OSError)):apply_plan(plan)
    assert (target/'runtime/a.py').read_text()=='incumbent source'
    assert canary.read_text()=='external secret'


def test_git_pointer_and_audit_custody_never_enter_inventory(tmp_path):
    (tmp_path/'.git').write_text('gitdir: private metadata')
    (tmp_path/'.audit-handoff').mkdir();(tmp_path/'.audit-handoff/secret').write_text('retained source')
    (tmp_path/'runtime').mkdir();(tmp_path/'runtime/a.py').write_text('source')
    image=inventory(tmp_path)
    assert set(image['files'])=={'runtime/a.py'}
    assert '.audit-handoff' in image['excluded']


def test_physical_read_budget_and_missing_parent_have_no_write_effect(tmp_path):
    from runtime.secure_publish import read_physical_bytes
    target=tmp_path/'missing/child.bin'
    with pytest.raises(FileNotFoundError):read_physical_bytes(target)
    assert not target.parent.exists()
    target=tmp_path/'large';target.write_bytes(b'12345')
    with pytest.raises(ValueError,match='budget'):read_physical_bytes(target,max_bytes=4)


def test_successful_port_retains_exact_preimage_and_noncertificate_receipt(tmp_path):
    import json
    source,target,plan=plan_fixture(tmp_path)
    receipt=apply_plan(plan)
    recovery=__import__('pathlib').Path(receipt['recovery'])
    assert (recovery.parent/'00000.before').read_text()=='incumbent source'
    journal=json.loads(recovery.read_text())
    assert journal['completed'] is True and journal['release_certified'] is False
    assert journal['published']==['runtime/a.py']
    assert receipt['deletes']==[]


def test_partial_interruption_retains_recovery_without_rolling_back_external_edits(tmp_path,monkeypatch):
    import json
    import scripts.rollout.integration_plan as owner
    source,target,plan=plan_fixture(tmp_path)
    (source/'runtime/b.py').write_text('second new');(target/'runtime/b.py').write_text('second old')
    plan['files'].append(dict(path='runtime/b.py',before_sha256=digest(target/'runtime/b.py'),after_sha256=digest(source/'runtime/b.py'),disposition='port',review_note='Reviewed fixture'))
    publish=owner.atomic_write_bytes
    def interrupt(path,raw):
        if path==target/'runtime/b.py':raise OSError('controlled second publication failure')
        return publish(path,raw)
    monkeypatch.setattr(owner,'atomic_write_bytes',interrupt)
    with pytest.raises(OSError,match='controlled'):owner.apply_plan(plan)
    assert (target/'runtime/a.py').read_text()=='reviewed new source'
    assert (target/'runtime/b.py').read_text()=='second old'
    journals=list((target/'.tmp/rollout-integration').glob('pacifyx-*/recovery.json'))
    assert len(journals)==1
    journal=json.loads(journals[0].read_text())
    assert journal['completed'] is False and journal['published']==['runtime/a.py']
    assert (journals[0].parent/'00001.before').read_text()=='second old'


def test_clean_managed_project_cannot_bypass_release_commissioning(tmp_path):
    from runtime.test_profiles import require_processing_stage,ProcessingOrderBlocked
    # The managed-project marker lives in the canonical control directory; a
    # marker planted under the legacy spelling is not a managed project and
    # would let this guard be skipped without ever exercising it.
    marker=tmp_path/'.agentic_engineering_os_px/project-record.json';marker.parent.mkdir();marker.write_text('{}')
    with pytest.raises(ProcessingOrderBlocked,match='missing mandatory'):require_processing_stage(tmp_path,'certify')
