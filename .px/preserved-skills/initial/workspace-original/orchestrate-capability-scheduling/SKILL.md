---
name: orchestrate-capability-scheduling
description: Plan, prioritize, place, arbitrate, simulate, observe, and recover bounded engineering or agent work across dependencies, approvals, budgets, deadlines, resources, privacy boundaries, retries, and fallbacks. Use when multiple ready tasks or implementations compete for finite capacity and the scheduling decision must be explainable, replayable, acceptance-preserving, and isolated by project.
---

# Orchestrate Capability Scheduling

Keep startup metadata-only. After selection, load `references/capability-index.json`,
then load exactly one of the 30 referenced capability contracts. Load
`references/workflow-index.json` only when the request needs a composed workflow.

## Scheduling loop

1. Bind the request to one active project and immutable acceptance contract.
2. Normalize tasks, dependencies, policies, approvals, budgets, resource telemetry, deadlines, and capability advertisements.
3. Apply hard eligibility gates before any preference score.
4. Score eligible work with normalized, recorded factors and deterministic tie-breaking.
5. Produce an observe-only or shadow schedule before requesting execution authority.
6. Delegate leases, locks, tool effects, execution, evidence, and completion verification to their existing canonical owners.
7. Recompute after task, resource, approval, deadline, lease, or evidence changes.
8. Recover in order: bounded retry, alternate capability, alternate target, approved degraded mode, human escalation, compensation or rollback, safe stop.

## Non-negotiable boundaries

- Schedule pressure never weakens acceptance criteria, privacy, security, evidence, or approval gates.
- Dispatch is not completion. Only the outcome verifier may accept completion evidence.
- A retry with effects requires an idempotency key, verified transaction boundary, or approved compensation.
- Restricted work cannot move to external execution silently.
- Scheduling is project-scoped. Queues, leases, memory, budgets, and evidence cannot bleed across projects.
- The bundled runtime is deterministic and observe-only; it never invokes an executor or mutates canonical state.

Use `engineering_bootstrap.capability_scheduler:simulate_schedule` for schedule simulation.
The canonical workflows are in `orchestration/workflows/capability-scheduling.yaml`.
