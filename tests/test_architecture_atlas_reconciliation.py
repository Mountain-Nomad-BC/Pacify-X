from __future__ import annotations
import json

import ast
from pathlib import Path

from docs.architecture.tools import build_atlas
from scripts import clean_source_export


def test_repository_atlas_owner_targets_canonical_tree(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def capture(repo, out, reference, max_files, max_bytes, allow_repo_output):
        calls.append((repo, out, reference, max_files, max_bytes, allow_repo_output))

    monkeypatch.setattr(build_atlas, "build", capture)
    clean_source_export._rebuild_repository_atlas(tmp_path)
    atlas = tmp_path / "docs/architecture"
    assert calls == [
        (tmp_path, atlas, atlas / "reference", 100_000, 2 * 1024**3, True)
    ]


def test_atlas_precedes_final_classification_and_world_state() -> None:
    source = Path(clean_source_export.__file__).read_text(encoding="utf-8")
    module = ast.parse(source)
    owner = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_rebuild_candidate_projections_unlocked"
    )

    calls = [
        node
        for node in ast.walk(owner)
        if isinstance(node, ast.Call)
    ]

    atlas_lines = [
        node.lineno
        for node in calls
        if isinstance(node.func, ast.Name)
        and node.func.id == "_rebuild_repository_atlas"
    ]

    classification_lines = [
        node.lineno
        for node in calls
        if isinstance(node.func, ast.Name)
        and node.func.id == "classify_tree"
    ]

    world_lines = [
        node.lineno
        for node in calls
        if isinstance(node.func, ast.Name)
        and node.func.id == "write_world_state"
    ]

    assert len(atlas_lines) == 1
    assert len(classification_lines) == 1
    assert len(world_lines) >= 2

    assert atlas_lines[0] < classification_lines[0] < max(world_lines)


def test_atlas_inventory_excludes_mutable_control_roots() -> None:
    assert ".tmp" in build_atlas.SKIP_DIRS
    assert ".engineering-bootstrap" in build_atlas.SKIP_DIRS
    assert "evidence" in build_atlas.SKIP_DIRS


def test_atlas_inventory_excludes_release_control_outputs(tmp_path):
    root = tmp_path

    policy = root / "policies" / "release-artifact-policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {
                "control_output_paths": [
                    "registry/px_world_state.json",
                    ".px/mcp-runtime-probe.json",
                ],
                "control_output_prefixes": [
                    "registry/control-receipts/",
                ],
            }
        ),
        encoding="utf-8",
    )

    world = root / "registry" / "px_world_state.json"
    world.parent.mkdir(parents=True)
    world.write_text('{"mutable": 1}\n', encoding="utf-8")

    probe = root / ".px" / "mcp-runtime-probe.json"
    probe.parent.mkdir(parents=True)
    probe.write_text('{"mutable": 2}\n', encoding="utf-8")

    receipt = root / "registry" / "control-receipts" / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"mutable": 3}\n', encoding="utf-8")

    source = root / "runtime" / "stable_source.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    rows, excluded, _images = build_atlas.inventory(root)

    paths = {row["path"] for row in rows}
    exclusions = {item["path"]: item["reason"] for item in excluded}

    assert "runtime/stable_source.py" in paths

    assert "registry/px_world_state.json" not in paths
    assert ".px/mcp-runtime-probe.json" not in paths
    assert "registry/control-receipts/receipt.json" not in paths

    assert exclusions["registry/px_world_state.json"] == (
        "mutable release control output"
    )
    assert exclusions[".px/mcp-runtime-probe.json"] == (
        "mutable release control output"
    )
    assert exclusions["registry/control-receipts/receipt.json"] == (
        "mutable release control output"
    )


def test_atlas_control_output_bytes_do_not_change_source_inventory(tmp_path):
    root = tmp_path

    policy = root / "policies" / "release-artifact-policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {
                "control_output_paths": [
                    "registry/px_world_state.json",
                ],
                "control_output_prefixes": [],
            }
        ),
        encoding="utf-8",
    )

    source = root / "runtime" / "stable_source.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    world = root / "registry" / "px_world_state.json"
    world.parent.mkdir(parents=True)
    world.write_text('{"revision": "first"}\n', encoding="utf-8")

    first, _excluded, _images = build_atlas.inventory(root)

    world.write_text('{"revision": "second"}\n', encoding="utf-8")

    second, _excluded, _images = build_atlas.inventory(root)

    assert first == second

def test_atlas_repository_measurement_artifact_is_deterministic():
    """Canonical Atlas output must not persist runtime-dependent wall time."""
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "docs" / "architecture" / "tools" / "build_atlas.py"
    ).read_text(encoding="utf-8")

    assert '"wall_seconds": None' in source
    assert '"wall_seconds": round(time.monotonic() - started, 3)' not in source
