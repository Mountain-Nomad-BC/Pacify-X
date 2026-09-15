from __future__ import annotations

import json
from pathlib import Path

from runtime.affected_proof import build_affected_proof_plan, validate_proof_completion


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(tmp_path: Path):
    cards = tmp_path / "cards"
    _write(
        cards / "dag.json",
        {
            "nodes": [
                {"card_id": "A", "path": "A.json", "dependencies": []},
                {"card_id": "B", "path": "B.json", "dependencies": ["A"]},
                {"card_id": "C", "path": "C.json", "dependencies": ["B"]},
            ]
        },
    )
    for card_id, focused, affected, section in (
        ("A", "tests/test_a.py", "tests/test_b.py", "testing-governance"),
        ("B", "vector B", "tests/test_c.py", "structural-adversarial"),
        ("C", "tests/test_c.py", "tests/test_c.py", "testing-governance"),
    ):
        _write(
            cards / f"{card_id}.json",
            {
                "focused_tests": [focused],
                "affected_tests": [affected],
                "affected_sections": [section],
                "negative_cases": [f"negative {card_id}"],
            },
        )
    _write(
        tmp_path / "registry/test_group_index.json",
        {
            "groups": [
                {"group": "core-a-f", "members": ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]}
            ]
        },
    )
    _write(
        tmp_path / "registry/dependency_authority.json",
        json.loads(
            (Path(__file__).parents[1] / "registry/dependency_authority.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    return cards


def test_plan_computes_transitive_cone_ownership_sections_and_staleness(tmp_path: Path):
    fixture(tmp_path)
    plan = build_affected_proof_plan(
        tmp_path,
        ("A",),
        card_directory="cards",
        projection_invalidation={"stale": ({"output": "registry/stale.json"},)},
    )
    assert plan["direct_consumers"] == ("B",)
    assert plan["transitive_consumers"] == ("C",)
    assert plan["test_groups"] == ("core-a-f",)
    assert set(plan["sections"]) == {"testing-governance", "structural-adversarial"}
    assert plan["stale_projections"] == ("registry/stale.json",)
    assert not plan["broad_profile_allowed_during_repair"]


def test_focused_green_cannot_close_a_card_with_consumers(tmp_path: Path):
    fixture(tmp_path)
    plan = build_affected_proof_plan(tmp_path, ("A",), card_directory="cards")
    result = validate_proof_completion(
        plan,
        {
            "passed_focused_tests": plan["focused_tests"],
            "passed_negative_cards": ("A", "B", "C"),
        },
    )
    assert not result["valid"]
    assert any(item.startswith("downstream_not_green") for item in result["errors"])


def test_complete_proof_accepts_only_exact_affected_plan(tmp_path: Path):
    fixture(tmp_path)
    plan = build_affected_proof_plan(tmp_path, ("A",), card_directory="cards")
    result = validate_proof_completion(
        plan,
        {
            "passed_focused_tests": plan["focused_tests"],
            "passed_affected_tests": plan["affected_tests"],
            "passed_test_groups": plan["test_groups"],
            "passed_sections": plan["sections"],
            "passed_negative_cards": ("A", "B", "C"),
            "downstream_green_cards": ("B", "C"),
        },
    )
    assert result["valid"], result["errors"]
