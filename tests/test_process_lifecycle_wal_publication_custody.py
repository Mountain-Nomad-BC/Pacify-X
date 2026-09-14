"""Public acknowledgment must retain usable transaction images."""
import pytest

from runtime import wal_transaction as wal


@pytest.mark.parametrize('boundary', ['target:0:published', 'manifest:committed:published', 'journal:committed:published'])
@pytest.mark.parametrize('kind', ['after', 'before', 'manifest'])
def test_public_commit_rejects_corrupted_retained_image(tmp_path, boundary, kind):
    owner = wal.JsonWal(tmp_path / 'wal', tmp_path)
    for index in range(2):
        (tmp_path / f'{index}.txt').write_bytes(b'before')
    def corrupt(point):
        if point == boundary:
            state = 'committed' if point == 'journal:committed:published' else 'transactions'
            relative = 'manifest.json' if kind == 'manifest' else f'{kind}/0001.txt'
            (tmp_path / 'wal' / state / 'public' / relative).write_bytes(b'corrupt')
    with pytest.raises(wal.WalIntegrityError) as caught:
        owner.commit([wal.TextArtifact('state', tmp_path / '0.txt', 'after'),
                      wal.TextArtifact('state', tmp_path / '1.txt', 'after')],
                     transaction_id='public', fault_injector=corrupt)
    assert [(tmp_path / f'{index}.txt').read_bytes() for index in range(2)] == [b'after', b'after']
    assert caught.value.wal_outcome['acknowledgement'] == 'failed'
    assert caught.value.wal_outcome['publication'] == 'targets_published'
    assert any((tmp_path / 'wal' / state / 'public').is_dir() for state in ('transactions', 'committed'))
