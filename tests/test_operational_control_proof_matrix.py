from __future__ import annotations

import json
from pathlib import Path

from scripts.build_operational_control_proof_matrix import STAGES, build


ROOT = Path(__file__).resolve().parents[1]


def test_matrix_is_current_complete_and_never_self_attests_execution() -> None:
    expected = build(ROOT)
    current = json.loads((ROOT / "registry/operational_control_proof_matrix.json").read_text(encoding="utf-8"))
    assert current == expected
    assert current["control_count"] == 941
    assert current["authority"].endswith("not evidence that any probe ran or passed.")
    assert len({item["control_id"] for item in current["controls"]}) == current["control_count"]
    for item in current["controls"]:
        assert set(item["stage_policy"]) == set(STAGES)
        assert set(item["stage_policy"].values()) <= {"required", "not_applicable_with_evidence"}


def test_semantic_obligations_do_not_masquerade_as_rendered_ui() -> None:
    matrix = build(ROOT)
    by_kind: dict[str, set[str]] = {}
    for item in matrix["controls"]:
        by_kind.setdefault(str(item["kind"]), set()).add(str(item["evidence_mode"]))
    assert by_kind["persistence"] == {"contained_durability"}
    assert by_kind["reload_reopen"] == {"contained_restart"}
    assert by_kind["failure_recovery"] == {"contained_fault_injection"}
    assert by_kind["indicator"] == {"live_state_observation"}
    assert by_kind["action"] <= {
        "contained_ui_interaction", "contained_host_interaction",
        "contained_sidebar_interaction",
    }
