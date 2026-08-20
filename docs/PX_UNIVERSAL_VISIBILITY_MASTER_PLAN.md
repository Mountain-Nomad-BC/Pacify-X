# Pacify-X maximum-visibility and operational-completion master plan

Status: implementation program approved; planning baseline complete  
Goal ID: `px-universal-visibility-and-operational-completion`  
Plan version: `1.0`  
Date: 2026-08-11

## Outcome and truth boundary

The achievable target is not omniscience. Pacify-X cannot legitimately read model private reasoning, decrypt unrelated traffic, observe hosts where no sensor or agent is installed, or obtain facts an external provider does not expose. The completion target is therefore:

> Every admitted execution path is either mediated and fully correlated, independently observed with declared attribution limits, explicitly self-reported with attestation status, or blocked/marked as a visible blind spot. No unobserved path may be presented as verified, safe, free, idle, or complete.

This is the strongest defensible form of “universal visibility.” It covers actions, effects, ownership, state transitions, provider usage, cost, failures, and evidence while deliberately excluding prompts, file contents, terminal output, credentials, secrets, and private chain-of-thought unless a separate, explicit content-capture policy is ever approved.

## Source custody

| Source | SHA-256 | Disposition |
|---|---|---|
| `PX_0.4.4_SECOND_PASS_OPERATIONAL_HARDENING_PLAN.md` | `c25a72a81ca0e490bde75db888091d06183b109f4c8af88237af0542e18318c5` | All 28 findings mapped to punch cards |
| `PX_0.4.4_INDEPENDENT_ADVERSARIAL_AUDIT.md` | `420e4101f9aa461dc1f82f51d5d21bf830d4e1b1dac48f7442a5b6f75fbe831a` | All priority findings, visual work, and certification gates mapped |
| `PX_VSCODE_SIDEBAR_LIVE_OPERATIONS_CONSOLE_SPEC.md` | `390359dc1ce5f673f29793e8f8a62c112d250cd2061f604a5f36bbb07cd0fe74` | All 40 sections mapped to sidebar/projection/provider cards |

The source documents remain immutable intake evidence. This plan supersedes their version-specific sequencing but not their requirements.

## Current evidence-backed baseline

### Implemented foundations

- Pacify-X runtime validation currently passes and the canonical dashboard API reports 172 skills, 11 tools, 270 agents, 72 orchestrations, 983 graph records, 1,917 graph edges, and 141 test modules.
- Extension 0.5.0 adds a project-owned metadata-only activity ledger, hash-chain validation, actor presence, active operations, VS Code lifecycle listeners, PX-launched Codex correlation, automatic MCP call traces, and explicit MCP emit/read tools.
- The Activity dashboard supports bounded filters, human/JSON inspection, export, pause/resume, explicit unknown attribution, responsive layout, and integrity state.
- Existing controls include CSP, bounded local paths, claim/fencing behavior, safe cleanup revalidation, provider credential separation, local-only Ollama admission, Git mutation denial, and packaged MCP operation.

### Still open or partial

- The sidebar remains a static `TreeDataProvider` showing catalog counts and two commands; it is not the requested live operations console.
- The Playwright lane drives `tests/preview.html`, can silently skip without a specific Edge path, and does not certify an installed VSIX against the live runtime.
- Extension coordination still has age-only stale-lock removal, fallback-on-corrupt authoritative JSON, all-or-empty JSONL tail parsing, and no crash-consistent multi-file transaction journal.
- Webview messages enter a central switch without one strict discriminated schema registry.
- Process cancellation kills a direct child, not a proven process tree.
- Provider request, billing identity, spend, burn, budget, and fallback telemetry do not yet have a canonical runtime ledger or projection.
- Runtime modules `sidebar_projection.py`, `provider_activity.py`, `provider_budget.py`, and `operational_health.py` do not yet exist.
- `dashboard.js` and `dashboard.css` remain monolithic; CSS still depends on repeated selector override strata.
- README/preview numeric claims drift from the current canonical runtime.
- Audit bootstrap and bundle creation remain host/developer-path coupled.

## Target architecture

```text
admitted execution path
  -> mandatory mediation wrapper or admitted observer
  -> canonical px.operation-event/1 schema
  -> durable append-only event ledger + transaction/lock authority
  -> correlation/claim/provider/budget reconciliation
  -> operational health + blind-spot coverage model
  -> canonical dashboard/sidebar projections
  -> event subscription bridge
  -> dashboard, sidebar, MCP, CLI, doctor, evidence bundle
```

### Visibility tiers

| Tier | Meaning | Completion rule |
|---|---|---|
| A — mediated | PX owns the invocation wrapper | Start, progress/heartbeat, terminal state, effect receipt, provider usage, and identity correlate |
| B — independently observed | OS/IDE sensor sees an effect but not intent | Show the event with explicit attribution/confidence limits; never infer actor or success |
| C — declared/attested | External agent emits the PX contract | Verify identity/nonce/signature when available and label unattested reports |
| D — blind/unsupported | No admitted sensor can observe the path | Surface a coverage gap and block certification; optionally block execution where PX controls admission |

### Canonical event requirements

Every event must carry a schema version, event ID, correlation ID, parent correlation, actor/session/harness, accountable owner, task/claim/orchestration IDs, source, operation, lifecycle status, declared/observed effect, bounded scope references, provider/request/budget IDs when applicable, timestamps, duration, telemetry freshness, input/output hashes, previous-event hash, and content-capture classification. Unknown values stay unknown.

### Enforcement rule

For PX-controlled work, instrumentation is part of admission: no correlation identity or no observer means the operation is denied or visibly downgraded to `unverified`. OS-level sensors add defense in depth but never replace the authoritative mediation receipt. Optional ETW (Windows), audit/eBPF (Linux), and platform-supported macOS observers require explicit installation, least privilege, consent, bounded retention, and health reporting.

## Dependency-ordered waves

### Wave 0 — Contract and baseline

Freeze source custody, define the visibility/privacy contract, enumerate every execution route, establish the canonical event schema, and create the machine-readable coverage registry. This prevents later UI or sensor work from inventing incompatible meanings.

Gate: every advertised path has an owner, effect class, observer/mediator, blind-spot state, retention class, and acceptance evidence definition.

### Wave 1 — Durable truth

Harden authoritative state parsing, leases, event chains, transaction journaling, invariants, migrations, recovery, and retention classification before increasing event volume.

Gate: crash/fault injection at every write boundary recovers deterministically or fails closed without state substitution or split brain.

### Wave 2 — Complete mediation and telemetry

Create the operational event bus and SDK, converge runtime/extension/MCP listeners, supervise process trees, maintain agent heartbeats, route provider invocations through one gateway, account for spend/budgets/fallbacks, and add optional OS observers plus a coverage reconciler. Add canonical inventories for system tools, real virtual environments, and secret-safe `.env` configuration relationships.

Gate: every admitted test path yields a complete correlated trace; every intentionally unmediated path appears as a blind spot or is denied.

### Wave 3 — Canonical projections and sidebar

Build truthful health/provider/budget/sidebar projections, subscribe the extension to revisions, validate messages, and replace the static sidebar with the specified mission-status console. Add a Packages & Environments surface that visibly distinguishes active, inactive, stale, broken, unknown, and deletion-blocked virtual environments.

Gate: idle, active, blocked, stale, degraded, recovering, disconnected, provider-active, fallback-active, and budget-exhausted states are driven by canonical fixtures and live events.

### Wave 4 — Failure survival and operational truthfulness

Finish Ollama stream faults, discovery freshness/ambiguity, cleanup races, async/event-loop work, per-control transition receipts, one consistent status taxonomy, governed tool/virtual-environment lifecycle operations, and secret-safe `.env` lifecycle visibility in the package tracker.

Gate: deterministic hostile fixtures either recover or emit exact diagnosis and retained evidence.

### Wave 5 — UI structural and visual completion

Use expand -> migrate -> contract batches to split the dashboard renderer and canonicalize CSS layers before final visual refinement. Preserve safety, keyboard, high contrast, reduced motion, touch, trackpad, and object-level deep links throughout.

Gate: no core selector is governed by source-order warfare; every surface has an independent module, contract test, visual baseline, and accessibility result.

### Wave 6 — Exact-artifact certification and release

Bootstrap hermetically, build once, install and test the exact VSIX, run live-runtime operations, restart, fault-inject, exercise supported platforms, enforce performance/cardinality gates, run PX Doctor, and produce independently verifiable evidence and attestations.

Gate: exact tested bytes equal distributed bytes, all required lanes executed without skips, and every definition-of-done item has current evidence.

## Tracer-bullet path

The first implementation slice must cross every layer before broad expansion:

1. Define `px.operation-event/1` and one provider-neutral correlation contract.
2. Emit one real task lifecycle through the durable event ledger.
3. Produce one canonical sidebar projection from that ledger.
4. Deliver it through an event-driven extension subscription.
5. Render Active Execution, one task, one agent, and no-provider-activity state.
6. Install the exact VSIX in a clean profile against the live runtime.
7. Mutate the real test task, verify the sidebar update, restart VS Code, verify recovery, and retain one evidence receipt.

Only after this vertical slice is green should additional listeners, providers, visual modules, or operating-system sensors expand the surface.

## DAG and current frontier

The detailed blocker graph is in `PX_UNIVERSAL_VISIBILITY_PUNCH_CARDS.md`. Its topological shape is:

```text
F01 -> F02 -> {F03,F04,R01,U01,U04}
{F03,F04} -> F05
F05 -> D01 -> D02 -> D03 -> D04 -> {D05,D06} -> D07
{F05,D04} -> O01 -> O02 -> {O03,O04,O05,O06,O07,O08,O10}
O08 -> O09
{O03..O10,D07} -> O11
{O01,O07,O09,O11} -> S01 -> S02 -> S03 -> S04 -> {S05..S10}
{D07,O11} -> {H01..H06}
{F04,H02} -> {O12,O13,O14}
{O12,O13,D07,H05} -> H07
{O14,D07,H05} -> H08
{S05,O12,O13,O14,H06,H07,H08} -> S11
U01 -> U02 -> U03
U04 -> U05 -> U06
{S10,S11,H01..H08,U03,U06,R01} -> R02 -> R03 -> R04 -> R05 -> R06
R04 -> R07
{R04,H04} -> R08
F05 -> R09
R01 -> R10
{D07,S01,O11} -> R11
{R05..R11} -> R12
```

The graph is acyclic by construction. With planning intake/baseline complete, the initial implementation frontier is `F03`, `F04`, `R01`, `U01`, and `U04`. Structural UI work must stay on an integration branch and preserve a continuously green installed-artifact tracer lane.

## Program-wide acceptance matrix

| Domain | Required proof |
|---|---|
| Coverage | Every admitted route classified A/B/C/D; no undeclared gaps |
| State | Corruption fails closed; journal recovery and migrations are deterministic |
| Concurrency | Live locks cannot be stolen; dead owners recover with receipts |
| Events | Hash chain, protected head, malformed-tail handling, ordering, clock/freshness tests |
| Agents | Heartbeat/stale state, claim/task correlation, truthful unknown attribution |
| Providers | Request receipts, billing identity, actual/unknown cost, budgets, burn, fallback, local/non-billable distinction |
| OS/IDE | Sensor health, privilege/consent, dropped-event counters, platform limits |
| System tools | Executable/path, version, source/install method, capabilities, project requirements, dependencies, environment requirements, health, last verification, update availability, conflicts, and trust/admission state are canonical and visible |
| Virtual environments | Python venv/virtualenv/Conda/Poetry/Pipenv and other admitted environment types have exact roots, interpreter/runtime, owner/project, package summary, health, last-used evidence, and active/inactive/stale/broken/unknown state; active state is tied to IDE selection, terminal activation, or a correlated live process rather than directory existence |
| `.env` awareness | Admitted `.env` files expose path/scope/owner, variable names and schema, required/optional state, consumer and secret-provider relationships, freshness, missing/duplicate/conflicting variables, and ignore/exposure validation; values never enter telemetry, evidence, logs, UI, or exports |
| Secret fingerprints | Low-entropy secret values are never protected with plain unsalted SHA-256. Value change detection is omitted by default; where justified it uses a keyed HMAC held by an approved secret source, with only the versioned comparison token retained |
| Environment lifecycle | Tool, virtual-environment, and `.env` mutations/deletions use exact targets, active-use checks, two matching snapshots, immediate pre-action revalidation, explicit confirmation, reversible quarantine where possible, and retained receipts |
| Sidebar | All 40 specification sections and 25 installed-VSIX scenario steps pass |
| Dashboard | Every control reaches authority, effect, state, acknowledgement, and receipt |
| Accessibility | Keyboard, focus, ARIA, forced colors, reduced motion, 200% zoom |
| Responsive | 260/300/340 sidebar and 480/760/1050/1440/1920 dashboard widths |
| Performance | Cold/warm projection, render, activation, event lag, and scale budgets pass |
| Release | Hermetic bootstrap; no required skip; exact VSIX installed/tested/published |
| Evidence | Human + JSON doctor, hashes, screenshots, logs, fault receipts, external checksum/attestation |

## Completion semantics

- A checkbox is complete only when its acceptance command/result and evidence identity are retained.
- “Implemented,” “tested,” “installed,” “live,” and “certified” are separate states.
- Three repeated matching blocker observations are required before a card or goal becomes blocked.
- A stale or unavailable sensor reduces coverage; it never silently reports healthy/idle.
- No global completion claim is permitted while a P0 card, a Tier-D admitted route, a required skipped lane, or an unresolved critical fault remains.
- Final completion requires `runtime.durable_state.close_specification_lifecycle` to accept the principles, specification, clarification, design, tasks, implementation evidence, and acceptance chain.

## Required deliverables

- Runtime: operation event schema/bus, provider activity and budget ledgers, operational health, sidebar projection, recovery/doctor, optional OS observers, and tool/environment/configuration contracts that never retain secret values.
- Package/environment tracker: system tools; actual virtual environments with observable active-use state; and admitted `.env` setups with variable-name/schema, consumer, secret-provider, exposure, freshness, conflict, drift, and reversible lifecycle metadata.
- Extension: strict contracts, event subscription, live sidebar webview, Packages & Environments surface, deep links, process supervisor, modular dashboard/CSS, coverage display.
- Tests: unit, contract, hostile fault, installed VSIX/live runtime, restart, multi-platform, accessibility, visual, performance, billing/fallback.
- Release: hermetic bootstrap, exact-artifact pipeline, generated build info, portable audit bundle, separate checksum and optional signed attestation.
- Evidence: punch-card receipts, source crosswalk, coverage matrix, doctor output, screenshots, installed file hashes, and final adversarial report.
