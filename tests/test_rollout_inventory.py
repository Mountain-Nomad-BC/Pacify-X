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
    for name in ('a.py', 'b.py'):
        (source / name).write_text('new')
        (target / name).write_text('old')
        files.append(dict(path=name, before_sha256=digest(target / name),
                          after_sha256=digest(source / name)))
    (target / 'b.py').write_text('concurrent edit')
    with pytest.raises(ValueError, match='Concurrent change'):
        apply_plan(dict(candidate=str(source), target=str(target), files=files))
    assert (target / 'a.py').read_text() == 'old'
    assert (target / 'b.py').read_text() == 'concurrent edit'


def test_overlay_never_removes_target_only_data(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir(); target.mkdir(); (target / '.git').write_text('worktree marker')
    (source / 'a.py').write_text('new')
    (target / 'preserved.txt').write_text('user data')
    apply_plan(dict(candidate=str(source), target=str(target), files=[
        dict(path='a.py', before_sha256=None, after_sha256=digest(source / 'a.py'))]))
    assert (target / 'a.py').read_text() == 'new'
    assert (target / 'preserved.txt').read_text() == 'user data'


def test_clean_checkout_does_not_admit_release_or_break_contract_collection(tmp_path, monkeypatch):
    from tests import test_release_certification
    monkeypatch.setattr(test_release_certification, 'ROOT', tmp_path)
    assert test_release_certification._release_campaign_admitted() is False
