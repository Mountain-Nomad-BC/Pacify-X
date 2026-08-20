# Architecture

```text
VS Code / Antigravity / compatible IDE
  ├─ Pacify-X webview (presentation and typed user intent only)
  └─ extension host
      ├─ PxBridge ───────────────> runtime.dashboard_api
      │                            canonical snapshots + paged catalogs
      ├─ CoordinationManager ────> <project>/.engineering-bootstrap/coordination/
      │                            DAG + leases + claims + events + handoffs + memory
      ├─ ContextBridge ──────────> Codex CLI (explicit; ChatGPT auth; API keys stripped)
      ├─ CleanupManager ─────────> admitted generated caches + retained receipts
      ├─ DiscoveryManager ───────> compact environment index + lazy hashed semantic shards
      ├─ EnterpriseManager ──────> separate offline packs, targets, guardrails, receipts
      ├─ optional Ollama ────────> loopback only; no service management
      └─ bundled stdio MCP ─────> same canonical API and coordination controller
```

## Authority and data flow

Pacify-X owns project/control-plane truth and the normalized catalog API. Git owns repository truth. The extension owns UI, IDE actor identity, typed dispatch, project coordination files, and lifecycle management of children it creates. It does not treat webview state or extension global storage as canonical.

Startup reads one compact snapshot. Detailed agents, skills, tools, workflows, and graph records are fetched only when their surface opens, in pages capped by the canonical API. Concurrent refreshes are coalesced and cached briefly.

Environment discovery follows the same bounded-startup rule. `current.json` contains counts, ontology, boundaries, hashes, and dataset descriptors only. The Workflows Environment Map and MCP load one hash-verified subject or per-extension contract at a time. The relation chain is `resource → capabilities → interface → requirements → effects → conflicts → policy → state`; manifest gaps stay unknown.

MS+Enterprise uses a second, explicitly namespaced catalog and project state model under `.engineering-bootstrap/enterprise/`. It does not reuse local agent IDs, skill IDs, connector state, authentication identity, billing identity, coordination records, or memory records. Offline metadata enablement cannot enable a connector. Cloud work requires a future admitted adapter and explicit target, authentication, billing, egress, mutation, cost, and receipt gates.

The default-off billable policy is separate from credentials and connectors. Enabling its master switch changes policy metadata only. A proposal must still satisfy provider allowlisting, local-first routing, task/session/day cost limits, token and GPU/CPU/RAM ceilings, escalation confidence, cache/reuse policy, and any required fresh human approval. This release does not implement an external billable executor.

## Coordination protocol

```text
task graph → dependency readiness → ownership/claim → IDE dispatch
          → progress receipts → conflict gate → reconciliation/release
          → handoff regeneration → layered memory update
```

Every state mutation holds an atomic project lock, re-reads the current revision, validates invariants, writes the next state atomically, appends a hash-linked event, and regenerates machine- and human-readable handoffs. Claims are target-scoped and leased. Overlapping unordered tasks are rejected at plan creation; overlapping active claims are rejected at runtime. Completion does not release authority silently: a task is reconciled explicitly before its lease is released.

## Memory layering

- L0 session: observations and transient work for one harness session.
- L1 project: source-linked facts, decisions, constraints, failures, and reusable project knowledge.
- L2 verified state: resume-critical task/claim/checkpoint facts tied to current project state.
- L3 system candidate: an explicit review queue only. No record is promoted into system truth automatically.

The portable handoff points to these records and the append-only event ledger. Native private-session transfer is not claimed.

## Activity observability

The extension subscribes to available VS Code document, workspace filesystem, terminal, task, test, debug, SCM, configuration, and extension lifecycle APIs. PX-launched Codex runs and every bundled MCP tool also emit correlated start/observation/terminal-state records. External agents can identify themselves through `pacify_activity_emit`; a filesystem event that cannot be tied to a PX session is explicitly assigned to an unknown watcher identity.

Each activity event contains actor/session/harness, operation, status, effect, source, optional task/claim/correlation links, relative scope references, duration, bounded safe metadata, and input/output hashes. Prompts, edited text, file contents, terminal output, tool payloads, secrets, credentials, and private reasoning are excluded. The trace is observational and never grants execution authority. Its retention window is declared, but no automatic destructive purge is implemented.
