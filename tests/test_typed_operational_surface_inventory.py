from __future__ import annotations

from pathlib import Path

from scripts.build_typed_operational_surface_inventory import build


ROOT = Path(__file__).resolve().parents[1]


def test_hidden_request_bindings_are_not_admitted_as_editable_controls() -> None:
    inventory = build(ROOT)
    control_ids = {
        control["control_id"]
        for surface in inventory["surfaces"]
        for control in surface["controls"]
    }
    for control_id in (
        "pxui.knowledge-core.field.learningPipelineId",
        "pxui.knowledge-core.field.rollbackExpectedHead",
        "pxui.knowledge-core.field.rollbackRecord",
        "pxui.knowledge-core.field.rollbackTarget",
        "pxui.skills-tools.field.fixedSkillDomain",
    ):
        assert control_id not in control_ids

    assert sum(surface["expected_control_count"] for surface in inventory["surfaces"]) == len(control_ids)
