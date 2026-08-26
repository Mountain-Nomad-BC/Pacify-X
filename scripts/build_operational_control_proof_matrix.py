"""Build the exhaustive, control-kind-aware operational proof contract.

This matrix is a test plan, never execution evidence.  It prevents a UI DOM
walk from claiming that a source contract, restart obligation, or recovery path
was proved merely because its owning surface rendered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


INVENTORY = Path("registry/operational_surface_inventory.json")
ACTION_INVENTORY = Path("extension/resources/ui/action-inventory.json")
TARGET = Path("registry/operational_control_proof_matrix.json")
STAGES = (
    "open_load", "display", "user_edit_action", "input_validation",
    "authorization", "backend_dispatch", "runtime_effect",
    "progress_reporting", "result_acknowledgement", "persistence",
    "reload_reopen", "failure_handling", "recovery_rollback",
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def action_requirement(control: dict[str, object], actions: dict[str, dict[str, object]]) -> dict[str, object]:
    parts = str(control["label"]).split(".")
    action = parts[1] if parts[0] == "dynamicRepair" and len(parts) > 1 else parts[0]
    contract = actions.get(action)
    if contract is None and action == "navigate":
        contract = {"mode": "ui-only", "effect": "none-outside-webview"}
    if contract is None and str(control["control_id"]).startswith("pxui.sidebar.action."):
        # The sidebar has its own typed inbound/outbound message contract rather
        # than the dashboard action registry.  Its interaction is still driven
        # in the contained sidebar browser and the live contributed view.
        contract = {"mode": "host", "effect": "host-ui-or-read"}
    if contract is None:
        raise ValueError(f"action control has no generated action contract: {control['control_id']}")
    host = contract["mode"] == "host"
    effect = str(contract["effect"])
    mutating = effect not in {"none-outside-webview", "read", "host-ui", "clipboard-write"}
    return {
        "evidence_mode": (
            "contained_sidebar_interaction"
            if str(control["control_id"]).startswith("pxui.sidebar.action.")
            else "contained_host_interaction" if host else "contained_ui_interaction"
        ),
        "probe": "render exact action class and every declared dataset variant; exercise validation, activation, and acknowledgement in a fresh contained state",
        "effect": effect,
        "requires_disposable_target": mutating,
        "requires_fault_injection": host,
        "requires_restart": mutating,
        "requires_real_external_authority": False,
        "state_role": "direct_control",
        "activation_condition": {
            "mode": "always",
            "trigger": "the owning surface and declared action variant are loaded",
        },
        "stage_policy": {
            stage: (
                "required"
                if stage in {"open_load", "display", "user_edit_action", "input_validation", "result_acknowledgement"}
                or host and stage in {"authorization", "backend_dispatch", "runtime_effect", "failure_handling"}
                or mutating and stage in {"persistence", "reload_reopen", "recovery_rollback"}
                else "not_applicable_with_evidence"
            )
            for stage in STAGES
        },
    }


def indicator_role(label: str) -> str:
    normalized = re.sub(r"([a-z])([A-Z])", r"\1 \2", label).lower()
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    if tokens & {
        "error", "failed", "failure", "invalid", "mismatch", "missing",
        "blocked", "stale", "detached", "unavailable", "warning", "requires",
    } or {"not", "accepted"} <= tokens or {"not", "ready"} <= tokens:
        return "conditional_failure"
    if tokens & {"pending", "loading", "awaiting", "progress", "running"}:
        return "conditional_progress"
    if {"no", "match"} <= tokens or "empty" in tokens:
        return "conditional_empty"
    return "steady_state"


def semantic_requirement(kind: str, label: str) -> dict[str, object]:
    configurations = {
        "command": ("isolated_host_command", "invoke the exact registered command in an isolated VS Code host and observe completion or typed denial", True, True, False),
        "field": ("contained_ui_input", "resolve the exact field, exercise valid and invalid boundaries, and restore its prior value", False, False, False),
        "form": ("contained_ui_form", "exercise the complete form with invalid and valid values and observe dispatch/acknowledgement", True, True, False),
        "menu": ("contained_ui_navigation", "exercise keyboard and pointer selection, focus, and selected-state acknowledgement", False, False, False),
        "editor": ("contained_ui_editor", "edit, validate, switch representations, and prove round-trip state equivalence", True, True, True),
        "gesture": ("contained_ui_gesture", "perform the exact pointer or keyboard gesture and prove bounded state change plus reversal", False, True, False),
        "indicator": ("live_state_observation", "drive the owning state transition and observe the exact indicator enter and leave its declared state", False, True, False),
        "lifecycle": ("contained_runtime_lifecycle", "exercise the declared lifecycle path through terminal success and controlled failure/recovery", True, True, True),
        "persistence": ("contained_durability", "write to a disposable authoritative target, bind pre/post digests, and verify durable state", True, True, True),
        "reload_reopen": ("contained_restart", "persist in a disposable target, restart the owning boundary, and verify exact reconstruction", True, True, True),
        "failure_recovery": ("contained_fault_injection", "inject the declared failure, observe the surfaced terminal state, and prove recovery or rollback", True, True, False),
        "acknowledgement": ("live_acknowledgement", "invoke the producer and validate the exact typed acknowledgement and revision/count invariants", False, True, False),
    }
    if kind not in configurations:
        raise ValueError(f"unsupported operational control kind: {kind}")
    mode, probe, disposable, fault, restart = configurations[kind]
    state_role = indicator_role(label) if kind == "indicator" else "direct_control"
    stage_policy = {}
    for stage in STAGES:
        required = stage in {"open_load", "display", "result_acknowledgement"}
        if kind in {"field", "form", "menu", "editor", "gesture"} and stage in {"user_edit_action", "input_validation"}:
            required = True
        if kind in {"command", "form", "lifecycle", "persistence", "reload_reopen", "failure_recovery", "acknowledgement"} and stage in {"authorization", "backend_dispatch", "runtime_effect"}:
            required = True
        if kind in {"lifecycle", "persistence", "reload_reopen"} and stage in {"persistence", "reload_reopen"}:
            required = True
        if kind in {"command", "form", "editor", "gesture", "lifecycle", "persistence", "reload_reopen", "failure_recovery"} and stage in {"failure_handling", "recovery_rollback"}:
            required = True
        if kind == "indicator" and state_role == "conditional_failure" and stage in {"failure_handling", "recovery_rollback"}:
            required = True
        if kind == "indicator" and state_role == "conditional_progress" and stage == "progress_reporting":
            required = True
        if kind in {"command", "lifecycle"} and stage == "progress_reporting":
            required = True
        stage_policy[stage] = "required" if required else "not_applicable_with_evidence"
    return {
        "evidence_mode": mode,
        "probe": probe,
        "effect": "kind-specific declared contract",
        "requires_disposable_target": disposable,
        "requires_fault_injection": fault,
        "requires_restart": restart,
        "requires_real_external_authority": False,
        "state_role": state_role,
        "activation_condition": {
            "mode": "always" if state_role in {"direct_control", "steady_state"} else "conditional",
            "trigger": {
                "conditional_failure": "the owning failure state is intentionally produced in a contained target",
                "conditional_progress": "the owning operation is intentionally held in its reported in-progress state",
                "conditional_empty": "the owning bounded query or collection is intentionally placed in its empty state",
            }.get(state_role, "the owning surface and control are loaded"),
        },
        "stage_policy": stage_policy,
    }


def build(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    inventory_bytes = (root / INVENTORY).read_bytes()
    action_bytes = (root / ACTION_INVENTORY).read_bytes()
    inventory = json.loads(inventory_bytes)
    action_inventory = json.loads(action_bytes)
    actions = {str(item["action"]): item for item in action_inventory["actions"]}
    controls = []
    for surface in inventory["surfaces"]:
        for control in surface["controls"]:
            requirement = (
                action_requirement(control, actions)
                if control["kind"] == "action"
                else semantic_requirement(str(control["kind"]), str(control["label"]))
            )
            controls.append({
                "control_id": control["control_id"],
                "surface_id": surface["surface_id"],
                "kind": control["kind"],
                "source_refs": control["source_refs"],
                **requirement,
            })
    controls.sort(key=lambda item: str(item["control_id"]))
    ids = [str(item["control_id"]) for item in controls]
    if len(ids) != len(set(ids)) or len(ids) != sum(item["expected_control_count"] for item in inventory["surfaces"]):
        raise ValueError("proof matrix does not preserve the complete unique control denominator")
    matrix = {
        "schema_version": "px.operational-control-proof-matrix/1.0",
        "authority": "Executable proof requirements only; this artifact is not evidence that any probe ran or passed.",
        "inventory": {"path": INVENTORY.as_posix(), "sha256": digest(inventory_bytes), "inventory_id": inventory["inventory_id"]},
        "action_inventory": {"path": ACTION_INVENTORY.as_posix(), "sha256": digest(action_bytes), "action_count": action_inventory["action_count"]},
        "chain_stages": list(STAGES),
        "control_count": len(controls),
        "controls": controls,
    }
    return {**matrix, "matrix_sha256": digest(canonical(matrix))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    value = build(args.root)
    encoded = json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    target = args.root.resolve(strict=True) / TARGET
    if args.check:
        if not target.is_file() or target.read_bytes() != encoded:
            raise SystemExit("operational control proof matrix is stale")
    else:
        target.write_bytes(encoded)
    print(json.dumps({"path": str(target), "control_count": value["control_count"], "matrix_sha256": value["matrix_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
