---
name: analyze-repository-intelligence
description: Map repositories, symbols, dependencies, configuration, runtime paths, ownership, change impact, reproductions, migrations, and test scope. Use before modifying an unfamiliar codebase or when a defect or change crosses files, services, or configuration layers.
---

# Analyze Repository Intelligence

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

1. `inventory-repository`
2. `trace-relationships`
3. `form-testable-hypotheses`
4. `measure-change-impact`
5. `propose-minimal-safe-action`

## Boundary

Default to read-only analysis; never widen a patch or infer ownership without traceable repository evidence.

Use `references/scripts-index.json` to locate a deterministic helper interface. The
cross-domain orchestration registry is `orchestration/workflows/declared-suite.yaml`.
