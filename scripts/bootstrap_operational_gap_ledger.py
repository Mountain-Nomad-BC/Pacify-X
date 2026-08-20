"""Create the first lossless operational-gap ledger from retained and current findings."""

from __future__ import annotations

import json
from pathlib import Path
import re

from runtime.operational_gap_ledger import (
    LEDGER_RELATIVE,
    append_events,
    blank_interaction_chain,
    read_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
ACTOR = "codex-primary:operational-ledger-bootstrap"
AUDIT = Path("registry/operational_surface_audit_20260816.json")
PENDING: list[dict[str, object]] = []


def record(
    event_type: str,
    payload: dict[str, object],
    *,
    actor: str = ACTOR,
    timestamp: str | None = None,
) -> None:
    PENDING.append(
        {
            "event_type": event_type,
            "payload": payload,
            "actor": actor,
            "timestamp": timestamp,
        }
    )


def actions(path: str) -> list[str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    return sorted(set(re.findall(r'data-action=["\']([^"\']+)', text)))


def inventory_actions() -> list[str]:
    text = (ROOT / "extension/src/uiActionInventory.js").read_text(encoding="utf-8")
    return sorted(set(re.findall(r"^\s{2}([A-Za-z][A-Za-z0-9]*):\s*\[", text, re.MULTILINE)))


def register_surfaces() -> None:
    groups = {
        "dashboard": "extension/media/dashboard/42-core-surfaces.js",
        "projects": "extension/media/dashboard/42-core-surfaces.js",
        "agents": "extension/media/dashboard/43-catalog-surfaces.js",
        "skills-tools": "extension/media/dashboard/43-catalog-surfaces.js",
        "workflows": "extension/media/dashboard/44-operational-surfaces.js",
        "plugins": "extension/media/dashboard/44-operational-surfaces.js",
        "diagnostics": "extension/media/dashboard/45-system-surfaces.js",
        "assurance": "extension/media/dashboard/45-system-surfaces.js",
        "settings": "extension/media/dashboard/45-system-surfaces.js",
        "memory": "extension/media/dashboard/46-observability-surfaces.js",
        "activity": "extension/media/dashboard/46-observability-surfaces.js",
        "knowledge-core": "extension/media/dashboard/47-advanced-surfaces.js",
        "runtime-core": "extension/media/dashboard/47-advanced-surfaces.js",
        "knowledge-graph": "extension/media/dashboard/48-graph-surface.js",
        "sidebar": "extension/media/sidebar.js",
    }
    all_actions = inventory_actions()
    groups.update(
        {
            "agent-studio": "extension/media/dashboard/90-controller.js",
            "workflow-studio": "extension/media/dashboard/90-controller.js",
            "skill-studio": "extension/media/dashboard/90-controller.js",
            "studio-lifecycle": "extension/media/dashboard/90-controller.js",
            "dashboard-control-plane": "extension/src/uiActionInventory.js",
        }
    )
    for surface_id, source in groups.items():
        controls = actions(source) if source.endswith(".js") else []
        if surface_id == "dashboard-control-plane":
            controls = all_actions
        elif surface_id == "agent-studio":
            controls = [item for item in all_actions if item.startswith("agent") or item in {"openStudioDraft", "openStudioFromCatalog", "submitStudioDraft", "operateStudioRevision", "refreshHostModels"}]
        elif surface_id == "workflow-studio":
            controls = [item for item in all_actions if item.startswith("workflow") or item in {"openStudioDraft", "openStudioFromCatalog", "submitStudioDraft", "operateStudioRevision"}]
        elif surface_id == "skill-studio":
            controls = [item for item in all_actions if item.startswith("skill") or item in {"openStudioDraft", "openStudioFromCatalog", "submitStudioDraft", "loadSkillPackageEditor"}]
        elif surface_id == "studio-lifecycle":
            controls = [item for item in all_actions if item.startswith("studio") or item in {"openStudioRuns", "submitStudioAgentRun", "submitStudioWorkflowRun"}]
        record(
            "surface_registered",
            {
                "surface_id": surface_id,
                "name": surface_id.replace("-", " ").title(),
                "source_files": [source],
                "known_controls": sorted(set(controls)),
                "owner": "Pacify-X dashboard/sidebar control plane",
                "inventory_evidence": [source, "extension/src/uiActionInventory.js"],
            },
            actor=ACTOR,
        )


def classification(area: str) -> str:
    value = area.lower()
    if any(token in value for token in ("agent", "workflow", "skill", "editor", "builder")):
        return "editor"
    if any(token in value for token in ("sidebar", "layout", "responsive", "graph", "dashboard", "ui")):
        return "UI"
    if any(token in value for token in ("memory", "revision", "transaction", "storage", "cleanup")):
        return "persistence"
    if any(token in value for token in ("runtime", "execution", "placement", "gpu", "startup", "provider")):
        return "runtime"
    if any(token in value for token in ("copilot", "codex", "plugin", "integration", "installed")):
        return "integration"
    if any(token in value for token in ("documentation", "instruction", "ledger")):
        return "documentation"
    return "backend"


def discover(card: dict[str, object], *, timestamp: str | None = None) -> None:
    record("card_discovered", card, actor=ACTOR, timestamp=timestamp)


def historical_cards() -> None:
    audit = json.loads((ROOT / AUDIT).read_text(encoding="utf-8"))
    for item in audit["findings"]:
        chain = blank_interaction_chain("Historical audit did not retain item-level interaction-chain evidence; re-exercise is required.")
        card = {
            "gap_id": item["id"],
            "parent_surface": str(item.get("area") or "unclassified"),
            "feature": str(item.get("area") or "unclassified"),
            "control_action": "historical finding; exact visible action must be reconciled",
            "discovery_source": AUDIT.as_posix(),
            "discovered_at": audit["created_utc"],
            "discovered_by": "historical-operational-surface-audit",
            "source_refs": [{"path": AUDIT.as_posix(), "symbols": [item["id"]]}],
            "expected_behavior": item["acceptance"],
            "observed_behavior": item["finding"],
            "interaction_chain": chain,
            "classification": classification(str(item.get("area") or "")),
            "severity": str(item.get("severity") or "high").lower(),
            "operational_impact": item["finding"],
            "dependencies": [],
            "blockers": [],
            "assigned_owner": "unassigned",
            "tests_required": [item["acceptance"]],
            "completion_evidence": [],
            "reopen_reason": None,
            "defer_skip": None,
            "next_action": "Reproduce against the exact installed host and complete every interaction-chain stage.",
        }
        discover(card, timestamp=audit["created_utc"])
        record(
            "card_annotated",
            {
                "gap_id": item["id"],
                "note": "Imported without promoting the historical status; the prior status remains evidence input only.",
                "evidence": [{"reference": AUDIT.as_posix(), "claim": f"Legacy status was {item.get('status', 'unknown')}."}],
                "patch": {"next_action": "Reconcile exact current source and installed-host behavior before any state advancement."},
            },
            actor=ACTOR,
            timestamp=audit["created_utc"],
        )


def chain_for(*, present: tuple[str, ...] = (), partial: tuple[str, ...] = (), missing: tuple[str, ...] = ()) -> dict[str, dict[str, object]]:
    chain = blank_interaction_chain()
    for stage in present:
        chain[stage] = {"state": "present", "detail": "Direct source or live evidence confirms this stage.", "evidence": []}
    for stage in partial:
        chain[stage] = {"state": "partial", "detail": "The stage exists but does not satisfy the full operational contract.", "evidence": []}
    for stage in missing:
        chain[stage] = {"state": "missing", "detail": "No complete operational owner or evidence was found for this stage.", "evidence": []}
    return chain


def current_card(gap_id: str, surface: str, feature: str, control: str, expected: str, observed: str, refs: list[tuple[str, list[str]]], *, kind: str, severity: str, missing: tuple[str, ...], partial: tuple[str, ...] = (), blockers: list[str] | None = None, tests: list[str] | None = None) -> dict[str, object]:
    return {
        "gap_id": gap_id,
        "parent_surface": surface,
        "feature": feature,
        "control_action": control,
        "discovery_source": "current adversarial Agent/Workflow/UI trace 2026-08-16",
        "discovered_at": "2026-08-16T18:00:00Z",
        "discovered_by": "codex-primary + control_runtime_trace + punch_card_reconciliation",
        "source_refs": [{"path": path, "symbols": symbols} for path, symbols in refs],
        "expected_behavior": expected,
        "observed_behavior": observed,
        "interaction_chain": chain_for(present=("open_load", "display"), partial=partial, missing=missing),
        "classification": kind,
        "severity": severity,
        "operational_impact": observed,
        "dependencies": [],
        "blockers": blockers or [],
        "assigned_owner": "codex-primary",
        "tests_required": tests or [expected],
        "completion_evidence": [],
        "reopen_reason": None,
        "defer_skip": None,
        "next_action": "Complete the missing interaction-chain stages with targeted installed-host evidence.",
    }


def current_cards() -> None:
    common_missing = ("runtime_effect", "persistence", "reload_reopen", "failure_handling", "recovery_rollback")
    rows = [
        current_card("PX-OS-068", "workflow-studio", "canvas revisioning", "drag node; Save immutable candidate; Edit as new revision", "Canvas positions reopen exactly while remaining outside the executable semantic hash.", "Browser node positions are discarded on save and regenerated on reopen; a hash-bound editor-state sidecar is not complete.", [("extension/media/dashboard/90-controller.js", ["studioEditorPayload", "openStudioDraftModal"]), ("runtime/workflow_studio.py", ["WorkflowStudio.save_revision"])], kind="revisioning", severity="high", missing=("persistence", "reload_reopen", "recovery_rollback"), partial=("user_edit_action", "input_validation", "backend_dispatch")),
        current_card("PX-OS-069", "workflow-studio", "authority editor", "workflowAddBinding/workflowAddGrant and rename/remove", "Bindings, grants, adapters, evidence, cost, egress, and reference propagation are editable visually and round-trip.", "Authority definitions were JSON-only. A visual editor patch is in progress but has not been narrowly verified or reopened from persisted data.", [("extension/media/dashboard/90-controller.js", ["workflowAuthorityHtml", "updateWorkflowAuthorityFromControl"]), ("extension/media/dashboard/49-studio-editors.js", ["normalizeWorkflow", "validateWorkflow"])], kind="editor", severity="high", missing=common_missing, partial=("user_edit_action", "input_validation")),
        current_card("PX-OS-070", "workflow-studio", "immutable revision edit", "openStudioFromCatalog -> submitStudioDraft -> catalog reload", "An authenticated revision reopens losslessly, saves a distinct immutable version, preserves its predecessor, and reopens from disk.", "The source exposes Edit as new revision, but create-to-reopen equality and failure recovery have never been exercised.", [("extension/media/dashboard/90-controller.js", ["openStudioFromCatalog", "studioDraftResult"]), ("extension/src/studioCatalog.js", ["collectStudioCatalog"])], kind="revisioning", severity="critical", missing=("runtime_effect", "persistence", "reload_reopen", "failure_handling", "recovery_rollback"), partial=("open_load", "display", "user_edit_action", "input_validation", "authorization", "backend_dispatch")),
        current_card("PX-OS-071", "agent-studio", "host tools", "tool_binding_ids; preview/start", "Exact admitted host tools execute through host-retained authority with implementation/schema/effect/target attestation and receipts.", "Preflight hard-fails every nonempty tool binding and the host throws before the existing dispatch loop can run.", [("runtime/agent_runtime.py", ["test_candidate", "prepare_host_run"]), ("extension/src/extension.js", ["executeAdmittedHostModel"])], kind="runtime", severity="critical", missing=("runtime_effect", "result_acknowledgement", "persistence", "failure_handling", "recovery_rollback"), partial=("display", "input_validation", "backend_dispatch")),
        current_card("PX-OS-072", "agent-studio", "memory bindings", "memory_binding_ids; preview/start", "Governed memory bindings resolve through an attached authorized broker, inject bounded provenance, and retain retrieval evidence.", "Browser and Python preflight reject every nonempty memory binding; no runtime retrieval owner is connected.", [("extension/media/dashboard/49-studio-editors.js", ["validateAgent"]), ("runtime/agent_runtime.py", ["test_candidate", "preview"])], kind="runtime", severity="critical", missing=("backend_dispatch", "runtime_effect", "progress_reporting", "result_acknowledgement", "persistence", "reload_reopen", "failure_handling", "recovery_rollback")),
        current_card("PX-OS-073", "agent-studio", "agent handoff", "handoff_agent_ids; preview/start", "A handoff targets an exact admitted agent/run contract with bounded durable dispatch, acknowledgement, and recovery.", "Browser and Python preflight reject every nonempty handoff; no runtime dispatch owner exists.", [("extension/media/dashboard/49-studio-editors.js", ["validateAgent"]), ("runtime/agent_runtime.py", ["test_candidate", "preview"])], kind="runtime", severity="critical", missing=("authorization", "backend_dispatch", "runtime_effect", "progress_reporting", "result_acknowledgement", "persistence", "reload_reopen", "failure_handling", "recovery_rollback")),
        current_card("PX-OS-074", "agent-studio", "model policy round trip", "openStudioFromCatalog; operateStudioRevision", "Every runtime-consumed model policy field survives exact catalog reopen and equality checking.", "normalizeAgent drops max_total_input_tokens and timeout_seconds even though host execution consumes them.", [("extension/media/dashboard/49-studio-editors.js", ["normalizeAgent"]), ("extension/src/extension.js", ["executeAdmittedHostModel"])], kind="revisioning", severity="critical", missing=("persistence", "reload_reopen", "failure_handling"), partial=("open_load", "display", "input_validation", "runtime_effect")),
        current_card("PX-OS-075", "agent-studio", "visual topology editing", "agentSelectSection and topology nodes", "Typed topology nodes and edges add/remove/connect actual model, capability, tool, memory, handoff, authority, and validation definitions.", "The topology is a synthesized navigation diagram; clicking only scrolls to forms and relationships cannot be composed.", [("extension/media/dashboard/90-controller.js", ["upgradeAgentTopology", "agentSelectSection"])], kind="editor", severity="high", missing=("user_edit_action", "persistence", "reload_reopen"), partial=("display",)),
        current_card("PX-OS-076", "workflow-studio", "operational node vocabulary", "node palette and executor adapters", "Every visible node type has matching model, validation, scheduler, effect, failure, and trace semantics.", "Only task, validation, and approval plus five deterministic adapters are implemented; richer operational nodes are absent.", [("runtime/studio_models.py", ["WORKFLOW_NODE_KINDS"]), ("runtime/workflow_studio.py", ["_adapter_contract_reasons"]), ("extension/media/dashboard/90-controller.js", ["workflowEditorHtml"])], kind="runtime", severity="high", missing=("display", "user_edit_action", "input_validation", "backend_dispatch", "runtime_effect", "progress_reporting", "result_acknowledgement", "persistence", "reload_reopen", "failure_handling", "recovery_rollback")),
        current_card("PX-OS-077", "workflow-studio", "browser/Python schema parity", "Save immutable candidate", "Browser and Python use equivalent identity, version, authority, adapter, expiry, domain, and size rules.", "Browser normalization preserves case and omits several root/authority checks that Python normalizes or rejects.", [("extension/media/dashboard/49-studio-editors.js", ["safeToken", "validateWorkflow"]), ("runtime/studio_models.py", ["WorkflowDefinition", "WorkflowNode"])], kind="backend", severity="critical", missing=("failure_handling", "recovery_rollback"), partial=("input_validation", "backend_dispatch")),
        current_card("PX-OS-078", "workflow-studio", "lifecycle separation", "Validate + admit", "Structural validation and admission are separate approved state transitions with distinct receipts and catalog states.", "The workflow validate operation directly calls validate_and_admit and changes admission state.", [("extension/media/dashboard/90-controller.js", ["studioLifecycleModal"]), ("runtime/studio_api.py", ["studio_operation"]), ("runtime/workflow_studio.py", ["validate_and_admit"])], kind="backend", severity="critical", missing=("recovery_rollback",), partial=("authorization", "backend_dispatch", "persistence", "result_acknowledgement")),
        current_card("PX-OS-079", "studio-lifecycle", "version allocation", "Edit as new revision", "Next version is collision-free, prerelease-aware, and verified against the backend immediately before save.", "nextStudioVersion handles only exact x.y.z and can select an existing revision.", [("extension/media/dashboard/90-controller.js", ["nextStudioVersion"])], kind="revisioning", severity="high", missing=("input_validation", "backend_dispatch", "failure_handling", "recovery_rollback")),
        current_card("PX-OS-080", "studio-lifecycle", "approval cancellation", "host approval for lifecycle operations", "Cancellation returns a typed webview result, preserves exact session/modal state, and visibly acknowledges zero mutation.", "Several host approval cancellations break without notifying the webview after it already closed its modal.", [("extension/src/extension.js", ["studioOperation"]), ("extension/media/dashboard/90-controller.js", ["studioLifecycle"])], kind="recovery", severity="high", missing=("result_acknowledgement", "persistence", "reload_reopen", "recovery_rollback"), partial=("authorization", "failure_handling")),
        current_card("PX-OS-081", "agent-studio", "working draft persistence", "close/reload editor with unsaved changes", "Bounded working drafts retain dirty state, source revision hash, restore, and explicit discard without mutating revisions.", "Webview state retains history and graph filters only; unsaved Studio drafts disappear on close or reload.", [("extension/media/dashboard/90-controller.js", ["persistStudioMetadata", "closeModal"])], kind="persistence", severity="high", missing=("persistence", "reload_reopen", "failure_handling", "recovery_rollback")),
        current_card("PX-OS-082", "studio-lifecycle", "exact resume resolution", "studioRunAction resume", "Resume fetches and authenticates the exact subject/version independently of current catalog paging.", "Exact resume scans only the currently loaded catalog page and fails when that revision is absent.", [("extension/media/dashboard/90-controller.js", ["exactStudioCatalogPayload", "studioRunAction"])], kind="backend", severity="high", missing=("backend_dispatch", "reload_reopen", "failure_handling"), partial=("input_validation", "result_acknowledgement")),
        current_card("PX-OS-083", "workflow-studio", "durable node trace", "open runs/status/pause/resume and visual canvas", "Authenticated durable status updates project per-node checkpoint state onto the open canvas until terminal state.", "The overlay updates only when an operation result already includes node receipts; run-list/status responses do not drive it.", [("extension/media/dashboard/90-controller.js", ["workflowRunTrace", "studioOperationResult"])], kind="integration", severity="high", missing=("progress_reporting", "reload_reopen", "failure_handling"), partial=("display", "result_acknowledgement", "persistence")),
        current_card("PX-OS-084", "studio-lifecycle", "payload boundary", "reopen catalog record into editor", "Semantic payload, authority sidecar, editor state, runtime inputs, and derived catalog metadata have explicit non-lossy boundaries.", "normalizeAgent/normalizeWorkflow spread derived catalog fields into drafts while Python ignores unknown fields, so canonical JSON does not round-trip.", [("extension/media/dashboard/49-studio-editors.js", ["normalizeAgent", "normalizeWorkflow"]), ("extension/src/studioCatalog.js", ["studioRecord"])], kind="revisioning", severity="high", missing=("input_validation", "persistence", "reload_reopen", "failure_handling")),
        current_card("PX-OS-085", "installed-extension", "installed/source identity", "activate extension and sidebar protocol", "One exact installed version and its in-memory host files match current source before UI operation.", "Source is 0.6.19 while the retained VS Code install is 0.6.16 with a mixture of matching and stale files.", [("extension/package.json", ["version"]), ("extension/src/extension.js", ["activateImplementation"]), ("extension/src/sidebarView.js", [])], kind="integration", severity="blocker", missing=("reload_reopen", "failure_handling", "recovery_rollback"), partial=("open_load", "display", "backend_dispatch")),
        current_card("PX-OS-086", "installed-extension", "dashboard command activation", "pacifyX.openDashboard", "The contributed command registers before fallible initialization and lazily reports initialization failures when invoked.", "Command registration occurs late; any earlier activation exception rolls back and VS Code reports command not found.", [("extension/src/extension.js", ["activateImplementation", "pacifyX.openDashboard"]), ("extension/package.json", ["contributes.commands"])], kind="integration", severity="critical", missing=("open_load", "result_acknowledgement", "failure_handling", "recovery_rollback"), partial=("display", "backend_dispatch")),
        current_card("PX-OS-087", "knowledge-graph", "full eligible map load", "Full map; graphLoadAll", "A visible load-all control accumulates every eligible bounded page with progress, cancellation, and final denominators.", "The controller contains automatic load-all logic, but no rendered load-all control reaches it; Full map remains the first page.", [("extension/media/dashboard/90-controller.js", ["graphLoadAll", "graphResult"]), ("extension/media/dashboard/48-graph-surface.js", ["projection"])], kind="UI", severity="high", missing=("user_edit_action", "progress_reporting", "result_acknowledgement", "failure_handling"), partial=("open_load", "display", "backend_dispatch")),
        current_card("PX-OS-088", "knowledge-graph", "source record opening", "Inspect source record", "Source inspection opens the exact bounded source record when a physical path exists and explains non-file records.", "The action displays record metadata but cannot open its source file.", [("extension/media/dashboard/48-graph-surface.js", ["inspectGraphRecord"]), ("extension/media/dashboard/90-controller.js", ["inspectGraphRecord"])], kind="UI", severity="medium", missing=("runtime_effect", "result_acknowledgement", "failure_handling"), partial=("display", "user_edit_action")),
        current_card("PX-OS-089", "plugins", "plugin lifecycle", "install/update/enable/disable/uninstall/rollback", "PX either owns receipt-bound plugin lifecycle operations or clearly hands off to VS Code without claiming PX completion.", "Plugin controls mostly open the generic VS Code extension manager; PX does not retain lifecycle receipts or conflicts.", [("extension/media/dashboard/44-operational-surfaces.js", ["plugins"]), ("extension/src/extension.js", ["openExtensionsView"])], kind="host-owned", severity="high", missing=("input_validation", "authorization", "backend_dispatch", "runtime_effect", "progress_reporting", "result_acknowledgement", "persistence", "reload_reopen", "failure_handling", "recovery_rollback"), partial=("open_load", "display", "user_edit_action")),
        current_card("PX-OS-090", "diagnostics", "targeted repair", "inspect issue; review evidence; execute repair", "Each diagnostic traces cause to affected operation, exact evidence, targeted repair owner, acknowledgement, and last-good recovery.", "Diagnostics mainly redisplays embedded text and cannot open evidence or execute/acknowledge targeted repairs.", [("extension/media/dashboard/45-system-surfaces.js", ["diagnostics"]), ("extension/media/dashboard/90-controller.js", ["inspectDiagnostic"] )], kind="backend", severity="high", missing=("backend_dispatch", "runtime_effect", "progress_reporting", "result_acknowledgement", "persistence", "reload_reopen", "failure_handling", "recovery_rollback"), partial=("display", "user_edit_action")),
        current_card("PX-OS-091", "settings", "typed PX configuration", "edit PX settings", "Typed PX controls validate, save, acknowledge, and reopen exact values in context.", "Most settings delegate to generic VS Code settings and do not show field-specific save acknowledgements.", [("extension/media/dashboard/45-system-surfaces.js", ["settings"]), ("extension/src/extension.js", ["openSettings"])], kind="UI", severity="high", missing=("input_validation", "result_acknowledgement", "persistence", "reload_reopen", "failure_handling", "recovery_rollback"), partial=("display", "user_edit_action", "backend_dispatch")),
        current_card("PX-OS-092", "runtime-core", "canonical work-plane ownership", "dashboard.snapshot producer", "Every expensive producer is admitted through one bounded event/state/work-plane owner with progress and recovery.", "dashboard.snapshot remains classified legacy-direct and runtime records are inspection-only.", [("runtime/work_admission.py", ["PRODUCER_CATALOG"]), ("runtime/dashboard_api.py", ["snapshot"])], kind="runtime", severity="high", missing=("authorization", "progress_reporting", "recovery_rollback"), partial=("backend_dispatch", "runtime_effect", "persistence", "failure_handling")),
        current_card("PX-OS-093", "workflows", "coordination receipt acknowledgement", "claim/progress/reconcile/release", "Every coordination write renders its returned durable receipt and failure/cancellation state.", "Coordination mutations refresh state but do not consistently display the returned receipt.", [("extension/media/dashboard/90-controller.js", ["coordinationResult", "submitTaskProgress", "submitReconcile"])], kind="UI", severity="high", missing=("result_acknowledgement", "failure_handling"), partial=("authorization", "backend_dispatch", "runtime_effect", "persistence")),
        current_card("PX-OS-094", "dashboard-control-plane", "visible-action contract", "workflow/knowledge local actions", "Every rendered action is classified as UI-only or host-bound with a valid owner/effect/result contract.", "Concurrent edits placed five UI-only actions under nonexistent host message types; action inventory generation currently rejects them.", [("extension/src/uiActionInventory.js", ["workflowAddBinding", "knowledgeRollback"]), ("extension/scripts/build-ui-action-inventory.js", ["buildUiActionInventory"])], kind="backend", severity="critical", missing=("input_validation", "result_acknowledgement", "failure_handling"), partial=("display", "user_edit_action")),
    ]
    for card in rows:
        discover(card)
        for state, reason in (("reproduced", "Exact source path demonstrates the current behavior."), ("scoped", "Canonical owner and missing interaction stages are identified.")):
            record("card_transition", {"gap_id": card["gap_id"], "from_state": "discovered" if state == "reproduced" else "reproduced", "to_state": state, "reason": reason, "evidence": [{"reference": card["source_refs"][0]["path"], "claim": card["observed_behavior"]}]}, actor=ACTOR)
    for gap_id in ("PX-OS-068", "PX-OS-069", "PX-OS-094"):
        record("card_transition", {"gap_id": gap_id, "from_state": "scoped", "to_state": "approved", "reason": "The user previously authorized full repairs; this records that authority without treating it as verification.", "evidence": [{"reference": "conversation:user-approved-full-repairs", "claim": "Write authority was explicitly granted for repository repairs."}]}, actor=ACTOR)
        record("card_transition", {"gap_id": gap_id, "from_state": "approved", "to_state": "implementing", "reason": "Source edits began before the user paused implementation for the ledger upgrade.", "evidence": [{"reference": "git-working-tree:current", "claim": "The interrupted edit remains unverified and is recorded as implementing, not complete."}]}, actor=ACTOR)
        record("card_annotated", {"gap_id": gap_id, "note": "Implementation paused by explicit user instruction. No discovered branch may be dropped while the ledger and inventory are built.", "evidence": [{"reference": "attachment:pasted-text.txt", "claim": "Stop implementation temporarily and upgrade the punch-card system before continuing."}], "patch": {"next_action": "Resume only after the ordered ledger exists and the full known surface inventory is reconciled."}}, actor=ACTOR)


def main() -> int:
    ledger = ROOT / LEDGER_RELATIVE
    if ledger.exists():
        raise FileExistsError(f"Refusing to replace append-only ledger: {ledger}")
    PENDING.clear()
    record(
        "ledger_initialized",
        {
            "ledger_id": "PX-OPERATIONAL-GAPS-20260816",
            "scope": ["all visible surfaces", "all controls and interactions", "backend/runtime effects", "persistence/reopen/failure/recovery"],
            "authority": "User-directed lossless operational tracking; no certification or narrative completion substitution.",
        },
        actor=ACTOR,
    )
    register_surfaces()
    historical_cards()
    current_cards()
    append_events(ROOT, PENDING)
    snapshot = read_snapshot(ROOT)
    print(json.dumps({"ledger": LEDGER_RELATIVE.as_posix(), "snapshot": "registry/operational_gap_ledger.snapshot.json", "progress": snapshot["progress"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
