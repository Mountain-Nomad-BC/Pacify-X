---
name: govern-runtime-protocol-deployment
description: Probe hardware and serving backends, plan capacity and cost, validate model and protocol compatibility, import governed tools, route models, manage caches and batching, compare canaries, degrade safely, and package human handoffs. Use for runtime selection, protocol integration, or deployment decisions.
---

# Govern Runtime Protocol Deployment

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

1. `probe-live-capabilities`
2. `validate-contract-and-compatibility`
3. `model-capacity-cost-and-quality`
4. `stage-canary-with-fallback`
5. `observe-decide-and-handoff`

## Boundary

Do not trust cached network identity or stale capability claims; require live discovery, bounded canaries, explicit fallback, and human approval for material release effects.

Use `references/scripts-index.json` to locate a deterministic helper interface. The
cross-domain orchestration registry is `orchestration/workflows/declared-suite.yaml`.
