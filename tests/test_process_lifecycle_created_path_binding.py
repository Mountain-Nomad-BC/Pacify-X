"""Publication handoff refuses content, generation and lifecycle substitution."""
from pathlib import Path

import pytest

from runtime.resource_lifecycle import ResourceManager, RunState


@pytest.mark.parametrize('case', ['exact', 'content', 'generation', 'ended'])
def test_publication_binding_preserves_exact_owned_generation(tmp_path, case):
    manager = ResourceManager(tmp_path / 'state/ledger.json')
    target = tmp_path / 'request.json'
    record = manager.register_path(target, allowed_cleanup_root=tmp_path,
        project_id='fixture', run_id='run', lane_id='lane', creator='test')
    target.write_bytes(b'{"value":1}')
    expected = target.read_bytes()
    if case == 'content':
        target.write_bytes(b'{"value":2}')
    elif case == 'generation':
        manager.bind_created_path(record.resource_id, expected)
        target.rename(tmp_path / 'original.json')
        target.write_bytes(expected)
    elif case == 'ended':
        manager.mark_run_ended('run', RunState.COMPLETED)
    before = manager.ledger.path.read_bytes()
    if case != 'exact':
        with pytest.raises(ValueError):
            manager.bind_created_path(record.resource_id, expected)
        assert manager.ledger.path.read_bytes() == before
        assert target.exists()
    else:
        bound = manager.bind_created_path(record.resource_id, expected)
        assert bound.path_identity is not None
        manager.mark_run_ended('run', RunState.COMPLETED)
        receipt = manager.reclaim(record.resource_id, reason='fixture', apply=True)
        assert receipt.resources_reclaimed == 1
        assert not Path(bound.path).exists()
