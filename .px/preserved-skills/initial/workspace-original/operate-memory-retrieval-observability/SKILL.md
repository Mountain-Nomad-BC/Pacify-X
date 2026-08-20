---
name: operate-memory-retrieval-observability
description: Design isolated memory, ingestion, indexing, hybrid retrieval, reranking, context budgeting, provenance, retention, trace correlation, replay, and quality-drift controls. Use for grounded retrieval, agent memory, run reconstruction, telemetry, or scoped deletion.
---

# Operate Memory Retrieval Observability

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

1. `bind-project-and-subject-scope`
2. `validate-ingestion-and-provenance`
3. `retrieve-and-budget-context`
4. `record-trace-and-quality`
5. `retain-promote-or-purge-by-policy`

## Boundary

Never cross project or subject scope, promote unverified observations, or purge without an auditable scope and recovery policy.

Use `references/scripts-index.json` to locate a deterministic helper interface. The
cross-domain orchestration registry is `orchestration/workflows/declared-suite.yaml`.
