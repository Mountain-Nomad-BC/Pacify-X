"""Build the reviewed typed operational surface inventory from audit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


REPORT = Path("evidence/operational-gap-ledger/agent-studio-control-revision-20260816.json")
TARGET = Path("registry/operational_surface_inventory.json")
UI_ACTION_INVENTORY = Path("extension/resources/ui/action-inventory.json")
DASHBOARD_CONTROLLER = Path("extension/media/dashboard/90-controller.js")

DASHBOARD_SURFACE_BINDINGS = {
    "dashboard": "dashboard",
    "projects": "projects",
    "agents": "agents",
    "agent-studio": "agent-studio",
    "workflow-studio": "workflow-studio",
    "skill-studio": "skill-studio",
    "knowledgeGraph": "knowledge-graph",
    "skillsTools": "skills-tools",
    "workflows": "workflows",
    "plugins": "plugins",
    "memory": "memory",
    "activity": "activity",
    "diagnostics": "diagnostics",
    "assurance": "assurance",
    "studio-lifecycle": "studio-lifecycle",
    "settings": "settings",
    "knowledgeCore": "knowledge-core",
    "runtimeCore": "runtime-core",
}

# The reviewed surface report is a historical audit input.  Current rendered
# actions are an independent, generated contract and must not be silently lost
# when that report predates a control.  Variants below bind repeated/template
# actions to stable per-surface identities.  Generation fails closed when a
# current action contract has no typed surface owner.
CURRENT_ACTION_SURFACE_BINDINGS: dict[str, dict[str, list[str]]] = {
    "resumeWorkingStudioDraft": {
        "agent-studio": ["resumeWorkingStudioDraft"],
        "workflow-studio": ["resumeWorkingStudioDraft"],
        "skill-studio": ["resumeWorkingStudioDraft"],
    },
    "discardWorkingStudioDraft": {
        "agent-studio": ["discardWorkingStudioDraft"],
        "workflow-studio": ["discardWorkingStudioDraft"],
        "skill-studio": ["discardWorkingStudioDraft"],
    },
    "acceptStudioVersionSuggestion": {
        "agent-studio": ["acceptStudioVersionSuggestion"],
        "workflow-studio": ["acceptStudioVersionSuggestion"],
        "skill-studio": ["acceptStudioVersionSuggestion"],
    },
    "agentAddTopologyNode": {
        "agent-studio": [
            "agentAddTopologyNode.tools",
            "agentAddTopologyNode.handoffs",
            "agentAddTopologyNode.memory",
        ]
    },
    "agentRemoveTopologyNode": {"agent-studio": ["agentRemoveTopologyNode.row"]},
    "workflowAddNode": {
        "workflow-studio": [
            "workflowAddNode.task",
            "workflowAddNode.validation",
            "workflowAddNode.approval",
            "workflowAddNode.branch",
            "workflowAddNode.join",
        ]
    },
    "agentSelectSection": {
        "agent-studio": [
            "agentSelectSection.identity",
            "agentSelectSection.behavior",
            "agentSelectSection.model",
            "agentSelectSection.harness",
            "agentSelectSection.capabilities",
            "agentSelectSection.tools",
            "agentSelectSection.workflows",
            "agentSelectSection.memory",
            "agentSelectSection.authority",
            "agentSelectSection.tests",
            "agentSelectSection.approval",
            "agentSelectSection.candidate",
        ]
    },
    "agentCancelConnection": {"agent-studio": ["agentCancelConnection"]},
    "agentPortConnect": {"agent-studio": ["agentPortConnect"]},
    "agentRemoveEdge": {"agent-studio": ["agentRemoveEdge"]},
    "forkStudioCandidate": {
        "agent-studio": ["forkStudioCandidate"],
        "workflow-studio": ["forkStudioCandidate"],
        "skill-studio": ["forkStudioCandidate"],
    },
    "inspectMetric": {
        surface_id: ["inspectMetric"]
        for surface_id in (
            "dashboard", "projects", "agents", "knowledge-graph", "skills-tools",
            "workflows", "plugins", "memory", "activity", "diagnostics",
            "assurance", "settings", "knowledge-core", "runtime-core",
        )
    },
    "inspectRuntimeRecord": {
        "runtime-core": [
            "inspectRuntimeRecord.startup",
        ]
    },
    "openProjectModuleMap": {"projects": ["openProjectModuleMap"]},
    "disconnectCanonicalMemory": {"memory": ["disconnectCanonicalMemory"]},
    "graphLoadAll": {"knowledge-graph": ["graphLoadAll"]},
    "importCatalogDefinition": {
        "agents": ["importCatalogDefinition.agent"],
        "workflows": ["importCatalogDefinition.workflow"],
    },
    "setupStudio": {
        "agents": ["setupStudio"],
        "workflows": ["setupStudio"],
        "agent-studio": ["setupStudio"],
    },
    "compareSkillOriginal": {"skills-tools": ["compareSkillOriginal"]},
    "executeExtensionConflictResolution": {"plugins": ["executeExtensionConflictResolution"]},
    "executeExtensionEnablement": {"plugins": ["executeExtensionEnablement"]},
    "executeExtensionInstall": {"plugins": ["executeExtensionInstall"]},
    "executeExtensionRollback": {"plugins": ["executeExtensionRollback"]},
    "executeExtensionUninstall": {"plugins": ["executeExtensionUninstall"]},
    "executeExtensionUpdate": {"plugins": ["executeExtensionUpdate"]},
    "previewExtensionConflictResolution": {"plugins": ["previewExtensionConflictResolution"]},
    "previewExtensionEnablement": {"plugins": ["previewExtensionEnablement"]},
    "previewExtensionInstall": {"plugins": ["previewExtensionInstall"]},
    "previewExtensionRollback": {"plugins": ["previewExtensionRollback"]},
    "previewExtensionUninstall": {"plugins": ["previewExtensionUninstall"]},
    "previewExtensionUpdate": {"plugins": ["previewExtensionUpdate"]},
    "queryExtensionConflicts": {"plugins": ["queryExtensionConflicts"]},
    "inspectProjectMapRecord": {
        "projects": [
            "inspectProjectMapRecord.service",
            "inspectProjectMapRecord.route",
            "inspectProjectMapRecord.test-link",
            "inspectProjectMapRecord.untested-source",
            "inspectProjectMapRecord.unmapped-test",
        ]
    },
    "submitLearningObservation": {"knowledge-core": ["submitLearningObservation"]},
    "submitLearningPattern": {"knowledge-core": ["submitLearningPattern"]},
    "submitLearningHypothesis": {"knowledge-core": ["submitLearningHypothesis"]},
    "submitLearningTrial": {"knowledge-core": ["submitLearningTrial"]},
    "submitLearningResearch": {"knowledge-core": ["submitLearningResearch"]},
    "submitLearningFinalValidation": {"knowledge-core": ["submitLearningFinalValidation"]},
    "submitLearningReuse": {"knowledge-core": ["submitLearningReuse"]},
    "submitReleaseTask": {"workflows": ["submitReleaseTask"]},
}

NATIVE_VSCODE_COMMANDS = (
    "pacifyX.openDashboard",
    "pacifyX.refreshDashboard",
    "pacifyX.validateControlPlane",
    "pacifyX.createContextSnapshot",
    "pacifyX.openCleanupManager",
    "pacifyX.openSettings",
    "pacifyX.rotateStudioApprovalIdentity",
    "pacifyX.continueWithCodex",
    "pacifyX.cancelCodex",
    "pacifyX.refreshProviderStatus",
    "pacifyX.refreshOllama",
    "pacifyX.refreshEnvironment",
)

STRUCTURAL_CONTROLS: dict[str, dict[str, list[str]]] = {
    "dashboard-control-plane": {"menu": ["mainNavigation", "commandCenter", "informationTabs"]},
    "agents": {"menu": ["surfaceScope"], "form": ["catalogFilter"]},
    "agent-studio": {
        "menu": ["editorTabs", "graphNodes"],
        "form": ["candidateMetadata", "capabilityBinding", "effectGrant"],
        "editor": ["visualBuilder", "canonicalJson"],
    },
    "skills-tools": {"menu": ["capabilityTabs"], "form": ["semanticQuery", "catalogFilter"]},
    "skill-studio": {"form": ["candidateMetadata", "packageFile"], "editor": ["packageFile"]},
    "workflows": {
        "menu": ["surfaceScope", "environmentScope"],
        "form": ["catalogFilter", "parallelPlan", "claimTask", "taskProgress", "reconcileTask", "environmentLifecycle"],
    },
    "workflow-studio": {
        "menu": ["editorTabs", "nodePalette"],
        "form": ["candidateMetadata", "nodeInspector", "typedEdge", "capabilityBinding", "effectGrant"],
        "editor": ["visualGraph", "canonicalJson"],
    },
    "studio-lifecycle": {"menu": ["revisionLifecycle", "runControls"], "form": ["agentRunObjective", "workflowRunInputs"]},
    "knowledge-graph": {
        "menu": ["graphView", "layout", "depth"],
        "form": ["searchAndFilter", "savedView"],
        "editor": ["interactiveCanvas", "accessibleMap"],
    },
    "memory": {"form": ["captureMemory", "queryFilter"]},
    "activity": {"form": ["queryFilter"]},
    "diagnostics": {"form": ["punchFilter", "enterpriseCatalogFilter"]},
    "knowledge-core": {
        "form": ["proposal", "reject", "rollback", "learningObservation", "learningPattern", "learningHypothesis", "learningTrial", "learningResearch", "learningFinalValidation", "learningReuse"]
    },
    "runtime-core": {"form": ["cleanupSelection"]},
}

# Historical audit extraction treated every named input as a user-operable
# field. These values are intentionally hidden request bindings: users operate
# the visible parent action while the controller carries the exact identity.
# Admitting them as editable controls creates impossible proof requirements and
# falsely lowers the operational denominator.
HIDDEN_REQUEST_BINDINGS = {
    ("knowledge-core", "learningPipelineId"),
    ("knowledge-core", "rollbackExpectedHead"),
    ("knowledge-core", "rollbackRecord"),
    ("knowledge-core", "rollbackTarget"),
    ("skills-tools", "fixedSkillDomain"),
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _source_file(reference: str) -> str:
    return re.sub(r":\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*$", "", reference)


def _control(surface_id: str, kind: str, name: str, label: str, source_refs: list[str]) -> dict[str, object]:
    return {
        "control_id": f"pxui.{surface_id}.{kind}.{name}",
        "kind": kind,
        "label": label,
        "source_refs": source_refs,
    }


def _dashboard_navigation_surfaces(source: str) -> list[str]:
    surfaces: list[str] = []
    for declaration in ("visibleSurfaces", "advancedSurfaces"):
        match = re.search(rf"const\s+{declaration}\s*=\s*\[(.*?)\];", source, re.DOTALL)
        if match is None:
            raise ValueError(f"dashboard controller is missing {declaration}")
        surfaces.extend(re.findall(r"\[\s*['\"]([^'\"]+)['\"]\s*,", match.group(1)))
    if not surfaces or len(surfaces) != len(set(surfaces)):
        raise ValueError("dashboard navigation surface declarations are empty or duplicated")
    return surfaces


def build(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    report_path = root / REPORT
    report_bytes = report_path.read_bytes()
    overlay = json.loads(report_bytes)
    base_relative = Path(str(overlay["base_report"]))
    base_bytes = (root / base_relative).read_bytes()
    if hashlib.sha256(base_bytes).hexdigest() != overlay["base_report_sha256"]:
        raise ValueError("typed surface base report hash differs from the reviewed overlay")
    report = json.loads(base_bytes)
    report["surfaces"][str(overlay["surface_id"])] = overlay["surface"]
    action_inventory_path = root / UI_ACTION_INVENTORY
    action_inventory_bytes = action_inventory_path.read_bytes()
    action_inventory = json.loads(action_inventory_bytes)
    dashboard_controller_path = root / DASHBOARD_CONTROLLER
    dashboard_controller_bytes = dashboard_controller_path.read_bytes()
    dashboard_navigation_surfaces = _dashboard_navigation_surfaces(
        dashboard_controller_bytes.decode("utf-8")
    )
    action_contracts = {
        str(item["action"]): item for item in action_inventory.get("actions", [])
    }
    if len(action_contracts) != action_inventory.get("action_count"):
        raise ValueError("generated UI action inventory count or identity is inconsistent")

    dashboard_actions = report["surfaces"]["dashboard-control-plane"].setdefault("actions", [])
    for navigation_surface in dashboard_navigation_surfaces:
        typed_surface = DASHBOARD_SURFACE_BINDINGS.get(navigation_surface)
        if typed_surface is None or typed_surface not in report["surfaces"]:
            raise ValueError(
                "dashboard navigation references an unknown typed surface: "
                + navigation_surface
            )
        label = f"navigate.{navigation_surface}"
        if label not in dashboard_actions:
            dashboard_actions.append(label)

    for action, surface_bindings in CURRENT_ACTION_SURFACE_BINDINGS.items():
        if action not in action_contracts:
            raise ValueError(f"typed action binding references a missing current contract: {action}")
        for surface_id, labels in surface_bindings.items():
            if surface_id not in report["surfaces"]:
                raise ValueError(f"typed action binding references an unknown surface: {action}:{surface_id}")
            actions = report["surfaces"][surface_id].setdefault("actions", [])
            for label in labels:
                if label not in actions:
                    actions.append(label)

    typed_action_names = {
        str(label).split(".", 1)[0]
        for surface in report["surfaces"].values()
        for label in surface.get("actions", [])
    }
    unmapped_actions = sorted(set(action_contracts) - typed_action_names)
    if unmapped_actions:
        raise ValueError(
            "current rendered actions have no typed surface mapping: "
            + ", ".join(unmapped_actions)
        )
    surfaces: list[dict[str, object]] = []
    for surface_id, source in report["surfaces"].items():
        source_refs = list(source["source_refs"])
        controls: list[dict[str, object]] = []
        for plural, kind in (
            ("actions", "action"),
            ("commands", "command"),
            ("fields", "field"),
            ("gestures", "gesture"),
            ("indicators", "indicator"),
        ):
            for name in source.get(plural, []):
                if kind == "field" and (surface_id, str(name)) in HIDDEN_REQUEST_BINDINGS:
                    continue
                control_refs = source_refs
                if kind == "action":
                    contract = action_contracts.get(str(name).split(".", 1)[0])
                    rendered_in = contract.get("rendered_in", []) if contract else []
                    if rendered_in:
                        control_refs = [f"extension/{reference}" for reference in rendered_in]
                    elif surface_id == "dashboard-control-plane" and str(name).startswith("navigate."):
                        control_refs = [DASHBOARD_CONTROLLER.as_posix()]
                controls.append(_control(surface_id, kind, name, name, control_refs))
        for kind, names in STRUCTURAL_CONTROLS.get(surface_id, {}).items():
            for name in names:
                controls.append(_control(surface_id, kind, name, name, source_refs))
        if surface_id == "dashboard-control-plane":
            for name in NATIVE_VSCODE_COMMANDS:
                controls.append(_control(surface_id, "command", name, name, ["extension/package.json:contributes.commands"]))
        for index, label in enumerate(source.get("lifecycle", []), 1):
            controls.append(_control(surface_id, "lifecycle", f"path.{index}", label, source_refs))
        controls.extend(
            [
                _control(surface_id, "persistence", "authoritativeState", source["persistence_reload"], source_refs),
                _control(surface_id, "reload_reopen", "authoritativeState", source["persistence_reload"], source_refs),
                _control(surface_id, "failure_recovery", "surface", source["failure_recovery"], source_refs),
            ]
        )
        if source.get("acknowledgement"):
            controls.append(_control(surface_id, "acknowledgement", "surface", source["acknowledgement"], source_refs))
        controls.sort(key=lambda item: str(item["control_id"]))
        ids = [str(item["control_id"]) for item in controls]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate typed control ID on {surface_id}")
        surfaces.append(
            {
                "surface_id": surface_id,
                "name": surface_id.replace("-", " ").title(),
                "expected_control_count": len(ids),
                "expected_controls_sha256": hashlib.sha256(
                    json.dumps(ids, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
                "source_files": sorted(set(_source_file(ref) for ref in source_refs)),
                "source_refs": source_refs,
                "controls": controls,
                "interaction_profiles": list(source.get("profiles", [])),
            }
        )
    surfaces.sort(key=lambda item: str(item["surface_id"]))
    return {
        "schema_version": "px.operational-surface-inventory/2.0",
        "inventory_id": "pacify-x-typed-surfaces-20260820-r14",
        "authority": "User-directed expected inventory baseline, derived from a reviewed per-surface source trace and reconciled fail-closed with the current generated UI action contract.",
        "source_report": REPORT.as_posix(),
        "source_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "ui_action_inventory": UI_ACTION_INVENTORY.as_posix(),
        "ui_action_inventory_sha256": hashlib.sha256(action_inventory_bytes).hexdigest(),
        "ui_action_count": len(action_contracts),
        "dashboard_controller": DASHBOARD_CONTROLLER.as_posix(),
        "dashboard_controller_sha256": hashlib.sha256(dashboard_controller_bytes).hexdigest(),
        "dashboard_navigation_surface_count": len(dashboard_navigation_surfaces),
        "surfaces": surfaces,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    inventory = build(args.root)
    encoded = json.dumps(inventory, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    target = args.root.resolve(strict=True) / TARGET
    if args.check:
        if not target.is_file() or target.read_bytes() != encoded:
            raise SystemExit("typed operational surface inventory is stale")
    else:
        target.write_bytes(encoded)
    print(json.dumps({"path": str(target), "sha256": hashlib.sha256(encoded).hexdigest(), "surface_count": len(inventory["surfaces"]), "control_count": sum(item["expected_control_count"] for item in inventory["surfaces"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
