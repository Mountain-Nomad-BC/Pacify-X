# Pacify-X 0.4 repair and integration patch

This is the historical patch record for the handoff build. The canonical extension source now lives at repository-relative `extension/`; the former external development tree is preserved only as migration provenance.

## Pacify-X source patch

- Added `runtime/dashboard_api.py`, schema `2.0.0`, as the first-class dashboard integration boundary.
- Added bounded `snapshot` and paged `catalog` CLI commands for skills, tools, agents, workflows/bindings, and graph records.
- Added `tests/test_dashboard_api.py` to reconcile API counts against authoritative registries and prove complete pagination/search/workflow coverage.
- The API reports optional TurboVec honestly and retains deterministic lexical/metadata/graph fallback.
- Existing unrelated project-map and registry edits in the source tree were preserved.

## Extension repair

- Replaced direct extension registry parsing with `src/pxBridge.js`, a thin cached client of `runtime.dashboard_api`.
- Added `src/coordinationManager.js` with atomic project state, hash-linked events, DAG validation, owners, dependencies, file/area claims, leases, sessions, task handoffs, receipts, reconciliation, and layered memory.
- Expanded `server/source.mjs` to twenty-seven MCP tools backed by the same canonical API, coordination controller, lazy semantic Environment Map, guardrail evaluator, governed Team Fabric adapters, and separate MS+Enterprise state manager.
- Added the `parallel-planning-coordination` skill and orchestration resources.
- Rebuilt the webview to show complete paged/searchable lists and operable task, memory, validation, context, settings, and cleanup controls.
- Reworked cleanup to compare full deterministic tree hashes at scan, preflight, and immediately before disposition. Both Recycle Bin and permanent actions are explicitly confirmed and receipted.
- Hardened Codex child environments by case-insensitively stripping common billable provider keys. Workspace-write requests require an active project task claim.
- Fixed package/installer version drift: package, VSIX name, checksum generation, install, and installed-version verification derive from `package.json` version `0.4.0`.
- Added `registry/ms_enterprise_catalog.json` to the Pacify-X source and exposed its separately paged skills, agents, workflows, connectors, and models through `runtime.dashboard_api`.
- Added `src/enterpriseManager.js`. It stores only enterprise pack state, non-secret target aliases, receipts, and explicit auth/billing namespace labels under `.engineering-bootstrap/enterprise/`; it never stores credentials or writes to canonical memory.
- Added MS+Enterprise tabs and working offline pack, target, and readiness controls. No connector or paid service was enabled.
- Added the requested Settings master switch and hard billable-execution guardrails. The switch defaults off and never stores credentials, connects, or authorizes an execution by itself.
- Added read-only startup/change/manual environment discovery with a compact index, separate hash-verified JSON shards, per-extension capability contracts, and the ontology `resource → capabilities → interface → requirements → effects → conflicts → policy → state`.

## Coordination files

The extension creates these only inside the opened project:

```text
.engineering-bootstrap/coordination/
  state.json
  events.jsonl
  handoff.json
  HANDOFF.md
  claims/
  receipts/
  task-handoffs/
  memory/session/
  memory/project/
  memory/state/
  memory/system-candidates/
.engineering-bootstrap/enterprise/
  state.json
  events.jsonl
  evidence/
```

Coordination and enterprise state are separate cross-IDE sources of truth. Extension global storage is only a cache/pointer. System-candidate memory is review-only, and enterprise state never becomes canonical memory without explicit reviewed promotion.

## No billable API setup

The extension declares no OpenAI, Anthropic, Google, Azure, or other billable API credential setting. The billable-policy switch is authorization metadata only; no external executor exists in this release, and every default cost cap/provider allowlist fails closed. Codex execution is allowed only when the installed CLI reports ChatGPT authentication. Ollama is opt-in and loopback-only. The MCP server is local stdio.

## Rollback

- Uninstall with `Uninstall-PacifyX.ps1`.
- Revert extension/source files individually with version control if desired; do not use a destructive reset because unrelated user changes exist.
- Project coordination data is user/project state and is never automatically deleted by uninstall.

Final commands, hashes, and installed smoke evidence are recorded in `evidence/BUILD_REPORT.md` after packaging.
