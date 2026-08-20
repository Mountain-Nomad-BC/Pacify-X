---
name: execution-placement-decision
description: Decide whether a bounded workload should keep its current language/runtime, deployment/platform, or database/storage placement. Use when comparing migrations, sidecars, native workers, services, accelerators, hosting classes, or primary-plus-secondary storage patterns using baselines, total boundary cost, rollback, benchmarks, and promotion evidence.
---

# Execution Placement Decision

Use `runtime.execution_placement` as the CPU-authoritative decision runtime. Read
`resources/placement-policy.md` before proposing a candidate or promotion.

## Workflow

1. Classify exactly one mode: `language_runtime`, `deployment_platform`, or
   `database_storage`.
2. Record the current placement as the mandatory `keep_current` candidate and
   bind the decision to a current baseline hash.
3. Compare provider-neutral classes before selecting a named vendor or product.
4. Score correctness, latency, throughput, operability, portability, cost,
   maintainability, and reversibility; subtract serialization, network,
   consistency, operational, and migration boundary costs.
5. Fail closed on compatibility, correctness, baseline, or rollback gaps.
6. Prefer the smallest bounded unit: adapter, sidecar, projection, worker, or
   index before a primary-system migration.
7. Freeze the decision and benchmark the selected candidate against the exact
   current baseline.
8. Require hashed after-state, boundary, and rollback evidence before partial
   promotion. Production remains separately authorized.

## Runtime interface

- Decision: `runtime.execution_placement.decide_placement`
- Promotion gate: `runtime.execution_placement.promotion_gate`
- Learning/revision lifecycle: `runtime.learning_promotion`

## Boundaries

- A recommendation never executes or authorizes migration.
- `keep_current` is valid and is selected when evidence is weak or improvement
  does not clear the configured threshold.
- Filesystem, database mutation, serialization, cleanup safety, and destructive
  decisions remain CPU-authoritative.
- No provider is selected before a placement class wins under current evidence.
- Losing revisions, baselines, and rollback paths are retained.

