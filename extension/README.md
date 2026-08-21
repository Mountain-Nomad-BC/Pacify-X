# Pacify-X Control Plane for VS Code

Pacify-X 0.6.26 is a local-first control, coordination, and activity-observability plane for VS Code-compatible IDEs. It consumes the versioned `runtime.dashboard_api` supplied by Pacify-X, exposes complete paged catalogs, and keeps project-owned coordination, activity, and resume state in the repository so another IDE or agent can continue without relying on private editor storage.

No billable provider API is configured. A loud, default-off policy switch can permit separately configured providers to be evaluated, but it never creates credentials, connects, or spends money. Every proposed billable execution must still pass task/session/day cost caps, token and hardware ceilings, local-first routing, provider allowlisting, confidence, cache/reuse, and explicit-approval gates. Codex handoff uses an existing ChatGPT-authenticated Codex CLI and strips common API-key variables from bridge-owned children. Ollama support is optional, loopback-only, disabled by default, and never installed or started by the extension.

## Operating surfaces

- Twelve normal surfaces plus two advanced surfaces with a persistent vertical control rail.
- Complete, searchable, sortable, paged core catalogs whose live counts come from the current Pacify-X registries rather than documentation constants.
- Separate MS+Enterprise tabs and data model with 18 packs, 20 skills, 12 agents, 8 workflows, 10 connectors, and 2 provider records. Connectors, egress, mutation, credential reads, and billable services are disabled by default.
- A project-owned Environment Map that discovers installed VS Code extensions, contribution points, commands, local tools, Python packages, and npm packages at startup and on refresh. A compact index lazy-loads hash-verified subject and per-extension JSON contracts plus a semantic ontology/graph.
- Parallel planning with task DAG validation, dependency readiness, explicit ownership, file/area claims, cross-IDE leases, dispatch packets, progress receipts, conflict gates, reconciliation, and release.
- Rolling memory layered as session → project → verified state → system candidate. System candidates never become canonical automatically.
- A portable `HANDOFF.md`/`handoff.json`, append-only events, task handoffs, state hashes, and active-session heartbeats under `.engineering-bootstrap/coordination/`.
- A metadata-only Activity surface with actor presence, active operations, correlation/task links, source/effect/status filters, hash-linked events, and human/JSON inspectors. VS Code editor, filesystem, terminal, task, test, debug, SCM, extension, PX-launched Codex, and MCP lifecycle hooks feed it without retaining prompts, file contents, terminal output, secrets, or private reasoning.
- A bundled local stdio MCP server with 35 context, catalog, graph, hardware-telemetry, readiness, plugin, Git-boundary, coordination, task, activity, memory, environment-map, guardrail-evaluation, worker-doctor, WorkRoom, team-package, and enterprise tools.
- Governed generated-cache cleanup with individual or Select all selection, Recycle Bin or permanent disposition, three matching inventory points, and durable receipts.
- Operable controls for synchronization, validation, parallel planning, resume handoff, bounded context, settings, and cleanup.
- A touch- and trackpad-ready graph explorer with drag panning, two-finger movement, pinch/Ctrl+wheel/button/keyboard zoom, fit/reset controls, flow and orbit layouts, a minimap, path isolation, and a readable directional connection list.

## Install

Requirements: Node.js 22, npm, VS Code 1.132 or newer, Python 3.11–3.14, and a Pacify-X engine checkout containing `runtime/dashboard_api.py`.

From this directory, install lockfile-exact dependencies, test, package, verify, and install:

```powershell
npm ci --ignore-scripts
npm test
npm run package
Get-FileHash .\dist\pacify-x-vscode-0.6.26.vsix -Algorithm SHA256
.\Install-PacifyX.ps1
```

Or choose **Extensions: Install from VSIX...** and select `dist/pacify-x-vscode-0.6.26.vsix`. Compare its SHA-256 with `SHA256SUMS.txt` first. Reload the VS Code window after installation.

Open a Pacify-X workspace, or set `pacifyX.engineRoot` and `pacifyX.workspaceRoot` to bounded absolute paths. Run `python -m runtime.cli --root <engine-root> doctor --require operable`, then **Pacify-X: Open Control Plane**. If the command is unavailable after installation, run **Developer: Reload Window** and inspect **Output → Pacify-X**. The engine root must contain `runtime/dashboard_api.py`.

## Cross-IDE resume

Every compatible extension instance registers a distinct actor/session and reads the same project ledger. Before editing, claim a task and its declared file/area targets. A conflicting active lease blocks the second actor. Record progress, then reconcile or release the claim. Another VS Code-compatible IDE can open the same workspace and use **Memory → Open resume packet** or the bundled MCP `pacify_resume_handoff` tool.

Private extension storage contains only a cache/pointer; it is not authoritative. See [MCP host setup](resources/mcp/README.md) for a host that can run stdio MCP but cannot install the VSIX.

AI and agent integrations can call `pacify_activity_emit` with their actor/session/correlation identity and inspect the same bounded trace through `pacify_activity_observability`. Every MCP tool is also wrapped automatically, while agents operating outside VS Code or MCP remain unattributed unless they emit this contract. Activity data lives under `.engineering-bootstrap/coordination/activity/`; the declared retention window is informational because automatic destructive purge is intentionally disabled.

Open **Workflows → Environment Map** to browse the semantic graph, extensions, tools, Python packages, and npm packages. The canonical relation chain is `resource → capabilities → interface → requirements → effects → conflicts → policy → state`. Detection reads manifests without activating arbitrary extensions. Provider-specific inputs, outputs, permissions, and APIs remain explicitly unknown when a manifest does not declare them. See [Environment capability map](docs/ENVIRONMENT_CAPABILITY_MAP.md).

## Safety

Git remains authoritative for repository state. The extension reads Git status and blocks bridge-owned work during merge/rebase/cherry-pick/revert conflicts; it does not commit, reset, checkout, stash, merge, rebase, or push. Workspace-write Codex execution additionally requires a live task claim.

Cleanup is restricted to generated Python/test cache directories below the admitted engine root. Evidence, quarantine, links/reparse points, unknown data, protected roots, path escapes, stale inventories, and changed trees fail closed. Permanent deletion requires an explicit VS Code confirmation.

See [Architecture](docs/ARCHITECTURE.md), [Ownership](docs/OWNERSHIP_MAP.md), [Completion punch card](docs/COMPLETION_PUNCH_CARD.md), [MS+Enterprise second-pass punch card](docs/MS_ENTERPRISE_SECOND_PASS_PUNCH_CARD.md), [MS+Enterprise operator guide](docs/MS_ENTERPRISE_OPERATOR_GUIDE.md), [Environment capability map](docs/ENVIRONMENT_CAPABILITY_MAP.md), [Repair patch](docs/REPAIR_PATCH.md), and [Limitations](docs/LIMITATIONS.md).
