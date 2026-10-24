from pathlib import Path
import pytest
from runtime.effect_surface import discover_effect_surfaces


def calls(tmp_path, source):
    (tmp_path / "producer.py").write_text(source, encoding="utf-8")
    return [row["call"] for row in discover_effect_surfaces(tmp_path)]


@pytest.mark.parametrize("source", [
    "'abc'.replace('a', 'b')",
    "f'abc'.replace('a', 'b')",
    "x = 'abc'\nx.replace('a', 'b')",
    "def f():\n    x: str = 'abc'\n    return x.replace('a', 'b', 1)",
    "str = object()\n'abc'.replace('a', 'b')",
])
def test_only_proven_builtin_string_receiver_is_excluded(tmp_path, source):
    assert calls(tmp_path, source) == []


@pytest.mark.parametrize("source", [
    "import os\nos.replace('a', 'b')",
    "from pathlib import Path\nPath('a').replace('b')",
    "x = 'abc'\nx = attacker\nx.replace('a', 'b')",
    "x = 'abc'\ndef f(x):\n    x.replace('a', 'b')",
    "def f():\n    x = 'abc'\n    def mutate():\n        nonlocal x\n        x = attacker\n    mutate()\n    x.replace('a', 'b')",
    "x = 'abc'\nexec(payload)\nx.replace('a', 'b')",
    "class C(metaclass=Hostile):\n    x = 'abc'\n    x.replace('a', 'b')",
    "str = attacker\nstr('abc').replace('a', 'b')",
    "f'{attacker}'.replace('a', 'b')",
    "'abc'.replace('a', 'b', attacker)",
    "x = 'abc'\nfrom host import x\nx.replace('a', 'b')",
    "x = 'abc'\nfrom host import *\nx.replace('a', 'b')",
    "x = 'abc'\nrebind_globals()\nx.replace('a', 'b')",
    "x: annotation_rebinding_globals() = 'abc'\nx.replace('a', 'b')",
    "x = 'abc'\nattacker.trigger(x.replace('a', 'b'))",
    "if condition:\n    x = 'abc'\nx.replace('a', 'b')",
])
def test_ambiguous_or_actual_mutating_receivers_remain(tmp_path, source):
    assert any(call.rsplit('.', 1)[-1] == 'replace' for call in calls(tmp_path, source))


def test_inner_effect_is_not_hidden_by_pure_outer_method(tmp_path):
    assert calls(tmp_path, "'abc'.replace(path.write_text('new'), 'b')") == ['path.write_text']


def test_unknown_formatted_receiver_retains_inner_effect(tmp_path):
    assert set(calls(tmp_path, "f'{path.write_text(\"new\")}'.replace('a', 'b')")) == {'replace', 'path.write_text'}


def test_copy_and_link_surfaces_are_not_reinterpreted(tmp_path):
    assert set(calls(tmp_path, "value.copy()\nimport os\nos.link('a', 'b')")) == {'value.copy', 'os.link'}
