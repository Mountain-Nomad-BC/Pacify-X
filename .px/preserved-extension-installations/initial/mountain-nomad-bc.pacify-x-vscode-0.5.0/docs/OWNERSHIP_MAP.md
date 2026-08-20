# Ownership and reconciliation map

| Function | Canonical owner | Extension exposure | Status |
|---|---|---|---|
| Snapshot and catalog normalization | `runtime.dashboard_api` | Typed snapshot and lazy pages | Implemented |
| Skills and tools | Pacify-X registries/admission | Complete searchable catalog | Implemented |
| Agent inventory | Pacify-X agent registry/provider | Complete searchable catalog | Implemented; live jobs are labelled unavailable |
| Workflow authorities | Project orchestrations, skill workflows, execution bindings | Unified catalog and planning surface | Implemented |
| Project coordination | Project-owned coordination ledger | Plans, claims, leases, dispatch, receipts, reconciliation | Implemented |
| Rolling continuity | Project ledger plus layered memory records | Session → project → state → system candidate | Implemented; system promotion requires external review |
| Repository state | Git / VS Code Source Control | Read-only status and conflict gate | Implemented; mutation denied |
| VS Code context and UI | Extension host | Dashboard, commands, actor identity | Implemented |
| Cross-host tools | Bundled stdio MCP | 31 context/catalog/graph/telemetry/plugin/coordination/environment/guardrail/Team Fabric/MS+Enterprise tools | Implemented |
| MS+Enterprise catalog | `registry/ms_enterprise_catalog.json` | Separate Skills, Agents, Workflows, connector, and provider views | Implemented; metadata/control plane only |
| MS+Enterprise project state | `src/enterpriseManager.js` + `.engineering-bootstrap/enterprise/` | Offline pack state, non-secret targets, doctor and receipts | Implemented; separate from coordination/memory |
| Microsoft/cloud connectors | Their future admitted adapters and external tenants | Honest disabled/not-installed readiness | Not connected; no credentials or billable setup |
| Environment discovery | `src/discoveryManager.js` + VS Code manifests + fixed local probes | Lazy subjects, per-extension contracts, semantic graph, MCP | Implemented; detection is not admission or activation |
| Billable execution policy | Separate enterprise state + VS Code settings | Default-off switch and independent hard gates | Implemented; no external executor or credential store |
| Codex execution | Existing Codex CLI | Explicit portable handoff | Implemented; ChatGPT auth required, no API fallback |
| Local model chat | Existing Ollama service | Loopback VS Code LM provider | Optional, disabled by default |
| TurboVec | Pacify-X candidate accelerator | Honest availability/status | Not activated; deterministic fallback remains authoritative |
| Cleanup | Cleanup manager + Pacify-X lifecycle concepts | Select, triple equality gate, dispose, receipt | Implemented for admitted generated caches |
| Evidence and quarantine | Pacify-X policy/evidence authorities | Excluded from cleanup and VSIX | Protected |

The extension is symbiotic, not a second runtime: it calls the canonical source API and adds IDE-local presentation and a project-scoped coordination protocol. Any future controller must establish an owner, policy/admission decision, effect declaration, receipt, timeout/cancellation behavior, and recovery path before the UI enables it.
