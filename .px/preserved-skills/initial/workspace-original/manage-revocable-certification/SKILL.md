---
name: manage-revocable-certification
description: Reconcile manifests, detect duplicates and collisions, enforce completion cutlines, verify archives and packages, aggregate evidence, certify capabilities, revoke stale claims, calculate recertification impact, and convert field feedback into regressions. Use for integration and release readiness.
---

# Manage Revocable Certification

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

1. `freeze-scope-and-denominators`
2. `reconcile-owners-and-artifacts`
3. `run-independent-completion-gates`
4. `issue-hash-bound-certificate`
5. `monitor-revoke-and-recertify`

## Boundary

A certificate is revocable, scope-bound, and hash-bound; any material change or failed dependency invalidates affected claims until recertification.

Use `references/scripts-index.json` to locate a deterministic helper interface. The
cross-domain orchestration registry is `orchestration/workflows/declared-suite.yaml`.
