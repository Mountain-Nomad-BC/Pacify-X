---
name: engineer-verification-lab
description: Design and run unit, integration, contract, differential, property, metamorphic, fuzz, mutation, performance, judge-calibration, trajectory, and long-horizon evaluations. Use when correctness or behavioral quality needs adversarial, independent, or regression-grade evidence.
---

# Engineer Verification Lab

Load `references/capabilities-index.json` or `references/scripts-index.json` only after this domain is selected. Then load exactly one referenced contract file for the selected outcome; do not hydrate another domain unless a workflow dependency requires it.

## Workflow

1. Resolve project identity, target scope, constraints, and the exact outcome ID.
2. Load only that outcome's contract from `references/capability-contracts.json`.
3. Validate inputs, authority, budgets, consumers, recovery, and verification oracle.
4. Produce a dry-run plan using the ordered domain phases below.
5. Execute only approved effects and checkpoint after each material phase.
6. Run the outcome's positive, negative, failure, and recovery checks.
7. Emit hash-bound evidence; never equate routing or prose with implementation.
8. For a shipped script, execute the exact packaged file in an isolated fixture. A generic dispatcher, contract projection, import, syntax check, or upstream claim does not certify that file.

## Ordered phases

1. `define-observable-claim`
2. `select-independent-oracle`
3. `generate-positive-and-adversarial-cases`
4. `run-and-minimize`
5. `score-and-promote-regressions`

## Boundary

Keep evaluation data, scoring rules, and implementation under test independently reviewable; do not certify from a self-authored happy path alone.

Run `engineering-bootstrap tools certify` when the declared-suite exact-tool registry is in scope. Require a current hash match, direct load, positive behavior, and the registered fail-closed case before certifying each tool.

Use `references/scripts-index.json` to locate a deterministic helper interface. The
cross-domain orchestration registry is `orchestration/workflows/declared-suite.yaml`.
