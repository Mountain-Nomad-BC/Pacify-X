import pytest
from runtime.effect_surface import discover_effect_surfaces


def scan(tmp_path, source):
    (tmp_path / 'producer.py').write_text(source, encoding='utf-8')
    return discover_effect_surfaces(tmp_path)


@pytest.mark.parametrize('source,diagnostic', [
    ("open('p', 'w')", 'writable_open_mode'),
    ("open('p', mode='r+')", 'writable_open_mode'),
    ("p.open('xb')", 'writable_open_mode'),
    ("p.open(mode='a')", 'writable_open_mode'),
    ("from builtins import open as op\nop('p','wb')", 'writable_open_mode'),
    ("import io as streams\nstreams.open('p','a')", 'writable_open_mode'),
    ("open('p', mode)", 'unresolved_open_mode'),
    ("p.open(**options)", 'unresolved_open_mode'),
    ("os.write(fd, b'body')", 'descriptor_write'),
    ("from os import write as put\nput(fd,b'body')", 'descriptor_write'),
    ("file.write('body')", 'unresolved_stream_receiver'),
    ("file.writelines(['body'])", 'unresolved_stream_receiver'),
])
def test_write_surfaces_are_discovered(tmp_path, source, diagnostic):
    records = scan(tmp_path, source)
    assert any(r['effect'] == 'filesystem_mutation' and r['stream_discovery'] == diagnostic for r in records)


@pytest.mark.parametrize('source', [
    "open('p')", "open('p','rb')", "from pathlib import Path\nPath('p').open(mode='rt')",
    "from builtins import open as op\nop('p','r')",
    "def read():\n    with open('p','rb') as f:\n        f.write(b'cannot write')",
    "from pathlib import Path\ndef read():\n    f = Path('p').open()\n    f.writelines(['cannot write'])",
    "from pathlib import Path\nPath('p').open('r').write('cannot write')",
])
def test_known_read_only_open_does_not_invent_effect(tmp_path, source):
    assert scan(tmp_path, source) == []


def test_rebound_read_handle_is_unresolved(tmp_path):
    records = scan(tmp_path, "def act(other):\n    f=open('p','r')\n    f=other\n    f.write('body')")
    assert records[0]['stream_discovery'] == 'unresolved_stream_receiver'


def test_read_binding_in_other_function_does_not_hide_write(tmp_path):
    records = scan(tmp_path, "def read():\n    f=open('p','r')\ndef write(f):\n    f.write('body')")
    assert records[0]['stream_discovery'] == 'unresolved_stream_receiver'


def test_shadowed_builtin_is_not_proven_read_only(tmp_path):
    records = scan(tmp_path, "def act(open):\n    f=open('p','r')\n    f.write('body')")
    assert {r['stream_discovery'] for r in records} == {'unresolved_open_receiver', 'unresolved_stream_receiver'}


def test_unknown_open_receiver_does_not_prove_read_only(tmp_path):
    assert scan(tmp_path, "p.open('r')")[0]['stream_discovery'] == 'unresolved_open_receiver'


def test_starred_open_arguments_are_unresolved(tmp_path):
    assert scan(tmp_path, "open(*arguments)")[0]['stream_discovery'] == 'unresolved_open_mode'
