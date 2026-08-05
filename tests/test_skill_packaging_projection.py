from __future__ import annotations

import importlib.util
from pathlib import Path
import tomllib

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
    for skill in (ROOT / ".agents/skills").iterdir():
        if not skill.is_dir() or skill.name in generator.EXISTING_MANUAL_SKILLS:
            continue
        assert {
            item.relative_to(ROOT).as_posix() for item in generator._owned_files(skill)
        } <= declared


def test_nested_non_markdown_skill_resources_are_projected():
    generator = load_generator()
    rendered = generator.render((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    nested = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / ".agents/skills").glob("*/references/**/*")
        if path.is_file() and path.suffix.casefold() not in {".md"}
    ]
    assert nested
    for relative in nested:
        if relative.split("/")[2] not in generator.EXISTING_MANUAL_SKILLS:
            assert f'"{relative}"' in rendered


def test_canonical_manifest_proves_exact_skill_source_projection():
    manifest = generate_artifact_manifest(ROOT)
    result = verify_commissioned_skill_projection(
        ROOT,
        manifest,
        source_only=set(),
    )
    assert result["valid"], result["errors"]
    assert result["source_file_count"] == result["wheel_projected_count"]
    assert result["source_file_count"] == result["sdist_projected_count"]
