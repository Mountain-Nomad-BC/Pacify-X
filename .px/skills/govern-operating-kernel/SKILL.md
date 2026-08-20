---
name: govern-operating-kernel
description: Govern capability routing, typed execution, permissions, assumptions, claims, durable state, recovery, learning promotion, and independent verification. Use when a task needs explicit authority, evidence, failure handling, or resumable control-plane state.
---

# Govern Operating Kernel

Load `references/capabilities-index.json` or `references/scripts-index.json` only after this domain is selected. Then load exactly one referenced contract file for the selected outcome; do not hydrate another domain unless a workflow dependency requires it.

## Workflow

1. Resolve project identity, target scope, constraints, and the exact outcome ID.
2. Load only that outcome's contract from `references/capability-contracts.json`.
3. Validate inputs, authority, budgets, consumers, recovery, and verification oracle.
4. Produce a dry-run plan using the ordered domain phases below.
5. Execute only approved effects and checkpoint after each material phase.
6. Run the outcome's positive, negative, failure, and recovery checks.
7. Emit hash-bound evidence; never equate routing or prose with implementation.

## Ordered phases

1. `establish-scope`
2. `authorize-effects`
3. `execute-bounded-work`
4. `independently-verify`
5. `commit-evidence-and-state`

## Boundary

Deny effects outside the approved task scope; preserve prior durable state and require idempotency or compensation for repeatable work.

Use `references/scripts-index.json` to locate a deterministic helper interface. The
cross-domain orchestration registry is `orchestration/workflows/declared-suite.yaml`.
