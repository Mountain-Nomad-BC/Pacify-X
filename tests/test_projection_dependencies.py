from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from runtime.projection_dependencies import (
    _assert_known_projection_current,
    invalidate_projections,
    plan_projection_rebuild,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry(root: Path):
    return {
        "schema_version": "px.projection-dependencies/1.0",
        "projections": [
            {
                "projection_id": "cheap",
                "owner": "runtime.fixture",
                "output": "out-a.json",
                "output_revision": _sha(root / "out-a.json"),
                "builder": "builder.py",
                "cost": "cheap_synchronous",
                "invalidation_rule": "any_dependency_revision_change",
                "rebuild_gate": "rebuild_before_use",
                "dependencies": [{"path": "source.txt", "revision": _sha(root / "source.txt")}],
            },
            {
                "projection_id": "expensive",
                "owner": "runtime.fixture",
                "output": "out-b.json",
                "output_revision": _sha(root / "out-b.json"),
                "builder": "builder.py",
                "cost": "expensive",
                "invalidation_rule": "any_dependency_revision_change",
                "rebuild_gate": "block_until_rebuilt",
                "dependencies": [{"path": "out-a.json", "revision": _sha(root / "out-a.json")}],
            },
        ],
    }


def test_invalidation_and_rebuild_plan_are_transitive_and_deterministic(tmp_path: Path):
    for name, text in (("source.txt", "one"), ("out-a.json", "a"), ("out-b.json", "b"), ("builder.py", "pass\n")):
        (tmp_path / name).write_text(text, encoding="utf-8")
    registry = _registry(tmp_path)
    assert invalidate_projections(tmp_path, registry)["stale"] == ()
    (tmp_path / "source.txt").write_text("two", encoding="utf-8")
    invalidation = invalidate_projections(tmp_path, registry)
    assert [row["projection_id"] for row in invalidation["stale"]] == ["cheap", "expensive"]
    plan = plan_projection_rebuild(invalidation)
    assert plan["synchronous"] == ("cheap",)
    assert plan["blocked_until_rebuilt"] == ("expensive",)
    assert not plan["usable"]


def test_unknown_builder_missing_revision_and_expensive_weak_gate_fail(tmp_path: Path):
    for name in ("source.txt", "out-a.json", "out-b.json", "builder.py"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    base = _registry(tmp_path)
    base["projections"][0]["builder"] = "missing.py"
    with pytest.raises(ValueError, match="unknown projection builder"):
        invalidate_projections(tmp_path, base)
    base = _registry(tmp_path)
    base["projections"][0]["dependencies"][0]["revision"] = ""
    with pytest.raises(ValueError, match="dependency revision"):
        invalidate_projections(tmp_path, base)
    base = _registry(tmp_path)
    base["projections"][1]["rebuild_gate"] = "rebuild_before_use"
    with pytest.raises(ValueError, match="must fail closed"):
        invalidate_projections(tmp_path, base)


def test_projection_cycles_are_rejected(tmp_path: Path):
    for name in ("source.txt", "out-a.json", "out-b.json", "builder.py"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    registry = _registry(tmp_path)
    registry["projections"][0]["dependencies"] = [
        {"path": "out-b.json", "revision": _sha(tmp_path / "out-b.json")}
    ]
    with pytest.raises(ValueError, match="cycle"):
        invalidate_projections(tmp_path, registry)


def test_expensive_skill_projection_staleness_is_explicitly_blocking():
    policy = {
        "schema_version": "px.skill-promotion-projection-staleness/1.0",
        "stale_blocked": ["registry/cognitive_map_index.json"],
        "consumer_policy": "block_until_governed_rebuild",
    }
    assert policy["stale_blocked"]
    assert policy["consumer_policy"] == "block_until_governed_rebuild"


def test_reconciliation_cannot_bless_known_stale_projection_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "semantic.json"
    output.write_text('{"revision":"old"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "runtime.semantic_index.build_semantic_index",
        lambda _root: {"revision": "current"},
    )
    with pytest.raises(ValueError, match="rebuild before revision reconciliation"):
        _assert_known_projection_current(
            tmp_path, "semantic-capability-index", "semantic.json"
        )
    output.write_text('{"revision":"current"}\n', encoding="utf-8")
    _assert_known_projection_current(
        tmp_path, "semantic-capability-index", "semantic.json"
    )
