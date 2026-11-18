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


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_imported_sys_standard_stream_is_not_a_file_write(tmp_path, stream):
    assert scan(tmp_path, f"import sys\nsys.{stream}.write('status')") == []


@pytest.mark.parametrize('source', [
    "def publish(other):\n    other.stdout.write('file bytes')",
    "def publish(other):\n    other.stderr.write('file bytes')",
    "sys.stdout.write('unknown sys')",
    "import sys\ndef publish(sys):\n    sys.stdout.write('shadow')",
    "import sys as other\nsys.stdout.write('unbound sys')",
    "import sys\nsys.stdout = sink\nsys.stdout.write('redirected')",
    "def unrelated():\n    import sys\nsys.stdout.write('unbound outside function')",
    "import sys\nfrom other import sink as sys\nsys.stdout.write('foreign import')",
])
def test_stdio_spelling_without_current_provenance_keeps_mutation(tmp_path, source):
    records = scan(tmp_path, source)
    assert any(row['effect'] == 'filesystem_mutation' for row in records)


def test_io_alias_keyword_append_mode_remains_a_write(tmp_path):
    records = scan(tmp_path, "import io as streams\nstreams.open('p', mode='a')")
    assert records[0]['stream_discovery'] == 'writable_open_mode'


def test_stream_resolver_initialization_uses_a_constant_number_of_tree_walks(monkeypatch):
    import ast
    from runtime.effect_surface import _stream_effect_resolver
    original = ast.walk
    counts = []
    for size in (5, 100):
        tree = ast.parse('\n'.join(f'value_{i} = {i}' for i in range(size)))
        calls = []
        def walk(node):
            calls.append(node)
            return original(node)
        with monkeypatch.context() as patch:
            patch.setattr(ast, 'walk', walk)
            _stream_effect_resolver(tree)
        counts.append(len(calls))
    assert counts[1] <= counts[0] + 1, counts


# ---------------------------------------------------------------------------
# Session-7 analysis defects 2-5. Each test states the fact the defect got wrong,
# so a future change that reintroduces it fails here instead of being absorbed as
# a moved census figure. (Defects 2-4 live in effect_surface; defect 5 in
# output_root_classification and is pinned in test_output_root_classification.py.)


def test_io_alias_file_argument_is_not_read_as_the_mode(tmp_path):
    """Defect 2: `import io as streams` + `streams.open('p','a')` lost the write.

    The alias was indexed as a *bound method*, so the file argument was read as the mode
    and the write vanished. Two effects were possible: no record, or a write reported at
    the wrong provenance. The write must be reported with the mode that was actually used.
    """
    records = scan(tmp_path, "import io as streams\nstreams.open('p','a')")
    assert [r['stream_discovery'] for r in records if r['effect'] == 'filesystem_mutation'] == [
        'writable_open_mode'
    ]


def test_a_read_handle_bound_in_the_same_file_is_not_reported_as_a_write(tmp_path):
    """Defect 3: a handle bound solely by a read-only open was reported as a write.

    `shadowed` always contains the binding's own name, so every self-consistent handle
    looked ambiguous and the resolver fell through to `handle_write`. A read handle that
    is never rebound writes nothing and may not invent an effect.
    """
    records = scan(
        tmp_path,
        "def read():\n"
        "    with open('p', 'rb') as handle:\n"
        "        return handle.write(b'cannot write')",
    )
    assert records == []


def test_a_handle_bound_only_by_a_read_open_is_read_only_even_across_scopes(tmp_path):
    """Defect 3, scope part: a binding outside the writing scope still proves the handle."""
    records = scan(
        tmp_path,
        "handle = open('p', 'r')\n"
        "def act():\n"
        "    handle.write('cannot write')",
    )
    assert records == []


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_imported_standard_stream_write_is_not_a_filesystem_mutation(tmp_path, stream):
    """Defect 4: `sys.stdout.write` / `sys.stderr.write` were counted as file mutations.

    The process's own streams cannot name a repository destination, so a console line is
    not durable state. This is the defect that moved the census by six records.
    """
    records = scan(tmp_path, f"import sys\nsys.{stream}.write('status')\n")
    assert not any(r['effect'] == 'filesystem_mutation' for r in records)


def test_the_six_records_removed_by_the_stdio_fix_are_still_absent(tmp_path):
    """Defect 4, pinned to the three real files whose rows moved (census 04j -> 04k).

    The two other session-7 defects that could have masked this (2 and 3) moved no file's
    total; this test reads the real sources, so a revisited fix that reintroduces stdio
    mutation fails here even if the synthetic fixtures above keep passing.
    """
    from pathlib import Path
    from runtime.effect_surface import classify_source_file

    root = Path(__file__).resolve().parents[1]
    expected_lines = {
        'extension/scripts/owned_windows_native_input.py': {331},
        'runtime/studio_api.py': {1509, 1527},
        'runtime/vscode_model_bridge.py': {408, 411, 445},
    }
    for relative, lines in expected_lines.items():
        source = (root / relative).read_text(encoding='utf-8-sig')
        reported = {r['line'] for r in classify_source_file(source, relative)}
        assert not (reported & lines), (relative, sorted(reported & lines))
