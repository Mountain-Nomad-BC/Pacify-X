"""Ownership rebuilds derive from source rather than their previous output."""
import pytest
from runtime.python_surface_certification import certify_python_surfaces
from runtime.effect_surface import discover_effect_surfaces


def test_python_surface_rebuild_ignores_corrupt_previous_output(tmp_path):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'registry').mkdir()
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="fixture"\n', encoding='utf-8')
    source = tmp_path / 'tests/test_sample.py'
    source.write_text('def test_sample(): assert True\n', encoding='utf-8')
    before = certify_python_surfaces(tmp_path, {}, require_map_current=False)
    (tmp_path / 'registry/python_surface_ownership.json').write_text('{broken', encoding='utf-8')
    after = certify_python_surfaces(tmp_path, {}, require_map_current=False)
    assert after == before
    # A read-only validation still refuses malformed published authority.
    with pytest.raises(ValueError):
        certify_python_surfaces(tmp_path, {}, require_map_current=True)


def test_effect_discovery_ignores_previous_output_and_tracks_new_source(tmp_path):
    (tmp_path / 'runtime').mkdir()
    (tmp_path / 'registry').mkdir()
    source = tmp_path / 'runtime/owner.py'
    source.write_text('from pathlib import Path\nPath("x").write_text("x")\n', encoding='utf-8')
    before = discover_effect_surfaces(tmp_path)
    (tmp_path / 'registry/effect_surface_ownership.json').write_text('{broken', encoding='utf-8')
    assert discover_effect_surfaces(tmp_path) == before
    source.write_text('import subprocess\nsubprocess.run(["fixture"], timeout=1)\n', encoding='utf-8')
    assert discover_effect_surfaces(tmp_path) != before
