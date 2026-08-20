# Operational gap ledger

The authoritative operational work record is `registry/operational_gap_ledger.jsonl`. It is append-only and hash chained. `registry/operational_gap_ledger.snapshot.json` is a deterministic projection and may be rebuilt; it is never the authority for rewriting history.

This ledger records implementation truth. It is separate from release readiness, certification, packaging, and narrative progress reports.

## Stable identity and states

New cards use a locked `PX-OS-NNN` allocation. Imported test fixtures may use `PX-GAP-NNN`. IDs are never renumbered, deleted, silently merged, or reused.

The primary path is:

`discovered → reproduced → scoped → approved → implementing → implemented → narrowly_verified → integrated → operationally_verified → closed`

Alternative states are `blocked`, `deferred`, `superseded`, and `reopened`. Every transition records a reason, actor, timestamp, and evidence. Deferral requires an explicit reason, authority, dependency, and return condition. Implementation, verification, integration, and operational verification have additional admission evidence. A closed card retains its history. Contradictory evidence reopens the same ID and must identify stronger regression coverage.

## Interaction coverage

Every card carries all stages:

`open/load → display → user edit/action → input validation → authorization → backend dispatch → runtime effect → progress reporting → result acknowledgement → persistence → reload/reopen → failure handling → recovery/rollback`

Each stage is `present`, `partial`, `missing`, `not_applicable`, or `unknown`. New `present` and `partial` claims require evidence. Missing and unknown stages prevent `operationally_verified`.

## Surface and control coverage

The expected inventory is independently retained in `registry/operational_surface_inventory.json` and hash-bound into the ledger. Registration and later changes are distinct events. A source change updates only affected controls and then appends an expected-inventory revision bound to its predecessor.

A surface is examined only when every registered control has one evidence-backed `operational` or `gap` disposition. A `gap` disposition names one or more stable cards. An absent disposition remains explicitly unresolved.

Every card also has an explicit control-resolution truth. A card resolves through one or more typed controls, an append-only `aggregate_parent` scope whose declared child cards are all resolved, or an exact `non_visible_path` scope with source symbols. Aggregate and non-visible dispositions require authority, rationale, evidence, and a return condition; revisions are predecessor-hash-bound. A simultaneous explicit scope and typed-control binding is reported as a conflict instead of silently choosing one.

Historical evidence claims remain immutable. `card_evidence_attested` may bind one exact historical reference-and-claim identity to an artifact hash, size, and verification method. A second attestation for that identity is rejected rather than overwriting provenance.

## Agent reports and task switching

Agent reports are evidence inputs, not authority. Register the report and its immutable hash, then reconcile every declared finding exactly once as `card`, `operational`, or `duplicate`. The projection exposes unreconciled findings.

Before switching away from active work, append a work checkpoint with:

- the active card;
- what was learned;
- the exact next action;
- every unresolved branch card;
- supporting evidence.

Card relationships preserve child, blocker, dependency, duplicate, and supersession edges.

## Operator commands

Use the module entry point from the repository root:

```powershell
python -m scripts.operational_gap_ledger --root . validate
python -m scripts.operational_gap_ledger --root . progress
python -m scripts.operational_gap_ledger --root . project
```

Mutation commands accept a JSON object or `--payload -` on standard input:

- `register-surface`, `add-controls`, `replace-controls`, `register-surface-alias`
- `register-inventory`, `revise-inventory`
- `discover`, `annotate`, `transition`
- `set-control-scope`, `revise-control-scope`, `attest-evidence`
- `dispose-control`, `examine`
- `register-report`, `reconcile-report-finding`
- `relate-cards`, `checkpoint`

Append operations are process-serialized. The next event count and encoded byte size are checked before publication. Local evidence inside the repository is bound by SHA-256 when appended. The snapshot refreshes only after the authoritative event is durably published.

## Progress truth

Progress reports keep these dimensions separate:

- expected, registered, missing, drifted, and examined surfaces;
- known, disposed, operational, gap, and unresolved controls;
- total gaps and each current state;
- unassigned cards;
- evidence-deficient and cryptographically unbound cards;
- cards whose retained source references omit relevant symbols;
- cards with unregistered surfaces, no raw control links, or no valid control resolution;
- typed-control, aggregate-parent, and non-visible-path card counts, plus explicit-scope conflicts;
- registered, reconciled, and unreconciled report findings.

No combined completion percentage is authoritative.

## Verification boundary

During implementation, run only card-specific checks and the governed section for the changed control plane. Full validation, certification, release packaging, and clean export remain deferred until the operational ledger has no unresolved functional cards and every surface/control interaction has installed-host evidence.
