from __future__ import annotations

import importlib.util
from pathlib import Path
import tomllib

import pytest

from runtime.release_distribution import (
    generate_artifact_manifest,
    verify_commissioned_skill_projection,
)


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/migration/sync_skill_packaging.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("sync_skill_packaging", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_skill_projection_is_complete_and_idempotent():
    generator = load_generator()
    current = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    rendered = generator.render(current)
    assert rendered == generator.render(rendered)
    assert rendered == current
    config = tomllib.loads(rendered)
    declared = {
        item
        for values in config["tool"]["setuptools"]["data-files"].values()
        for item in values
    }
    for skill in (ROOT / ".px/skills").iterdir():
        if not skill.is_dir() or skill.name in generator.EXISTING_MANUAL_SKILLS:
            continue
        assert {
            item.relative_to(ROOT).as_posix() for item in generator._owned_files(skill)
        } <= declared
    for facade in (ROOT / ".px/skills").iterdir():
        if not facade.is_dir():
            continue
        facade_files = {
            item.relative_to(ROOT).as_posix() for item in generator._owned_files(facade)
        }
        assert facade_files <= declared
        assert any(
            target.startswith("share/engineering-bootstrap/.px/skills/")
            and facade.name in target
            for target in config["tool"]["setuptools"]["data-files"]
        )


def test_generator_refuses_a_duplicate_generated_section():
    generator = load_generator()
    current = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    generated = "\n".join(generator._generated_lines())
    duplicated = current.replace(generator.START, generated + "\n" + generator.START, 1)
    with pytest.raises(ValueError, match="markers are missing or duplicated"):
        generator.render(duplicated)


def test_nested_non_markdown_skill_resources_are_projected():
    generator = load_generator()
    rendered = generator.render((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    nested = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / ".px/skills").glob("*/references/**/*")
        if path.is_file() and path.suffix.casefold() not in {".md"}
    ]
    assert nested
    for relative in nested:
        if relative.split("/")[2] not in generator.EXISTING_MANUAL_SKILLS:
            assert f'"{relative}"' in rendered


def test_future_skill_overlay_renders_canonical_paths_before_publication(tmp_path):
    generator = load_generator()
    (tmp_path / ".px/skills/existing").mkdir(parents=True)
    (tmp_path / ".px/skills/existing/SKILL.md").write_text(
        "# Existing\n", encoding="utf-8"
    )
    staged = tmp_path / ".engineering-bootstrap/staged/demo"
    staged.mkdir(parents=True)
    (staged / "SKILL.md").write_text("# Future\n", encoding="utf-8")
    (staged / "resources").mkdir()
    (staged / "resources/data.json").write_text("{}\n", encoding="utf-8")
    current = '[tool.setuptools.data-files]\nplaceholder = ["README.md"]\n'

    rendered = generator.render(
        current,
        tmp_path,
        skill_overlays={"demo": staged},
    )

    parsed = tomllib.loads(rendered)
    values = {
        item
        for files in parsed["tool"]["setuptools"]["data-files"].values()
        for item in files
    }
    assert ".px/skills/demo/SKILL.md" in values
    assert ".px/skills/demo/resources/data.json" in values
    assert not any(".engineering-bootstrap/staged" in item for item in values)


def test_generator_preserves_suffix_and_refuses_malformed_markers():
    generator = load_generator()
    base = '[tool.setuptools.data-files]\nplaceholder = ["README.md"]\n'
    current = (
        base
        + generator.START
        + "\nold = [\"old\"]\n"
        + generator.END
        + "\n[tool.example]\nvalue = true\n"
    )
    rendered = generator.render(current)
    assert rendered.endswith("\n[tool.example]\nvalue = true\n")
    assert tomllib.loads(rendered)["tool"]["example"]["value"] is True
    for malformed in (
        base + generator.START + "\n",
        base + generator.END + "\n",
        base + generator.START + generator.START + generator.END,
    ):
        with pytest.raises(ValueError, match="markers"):
            generator.render(malformed)


def test_canonical_manifest_proves_exact_skill_source_projection():
    manifest = generate_artifact_manifest(ROOT)
    assert manifest["valid"], manifest["errors"]
    result = verify_commissioned_skill_projection(
        ROOT,
        manifest,
        source_only=set(),
    )
    assert result["valid"], result["errors"]
    assert result["source_file_count"] == result["wheel_projected_count"]
    assert result["source_file_count"] == result["sdist_projected_count"]
