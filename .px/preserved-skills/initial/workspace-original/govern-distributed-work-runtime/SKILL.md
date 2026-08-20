---
name: govern-distributed-work-runtime
description: Coordinate organization-scoped goals, atomic work checkout, multidimensional budgets, runtime placement, quotas, capability and secret leases, external jobs, and operator handoff without cross-project state bleed. Use for multi-project or multi-runtime execution, remote agents, notebooks, containers, MCP, A2A, or expensive operations.
---

# Govern Distributed Work Runtime

1. Bind work to an immutable organization, program, project, goal, task, and acceptance lineage. Project authority remains the execution boundary.
2. Reserve work with compare-and-swap semantics before dispatch. One work item has at most one active lease; terminal states are sticky.
3. Reserve cost, turns, model calls, duration, CPU, memory, disk, and accelerator capacity atomically. Reconcile actual use and release all remainder on success, failure, cancellation, and timeout.
4. Keep agent harness behavior separate from compute placement. Select runtimes only after hard capability, trust, locality, health, scope, quota, and user-presence filters.
5. Project secrets by value-free, scoped, expiring, revocable leases. Never persist secret values in receipts.
6. Lease tools, browser, notebook, sandbox, MCP, and remote capabilities independently of availability. Tool discovery is not authorization.
7. Qualify external identifiers by source, reject collisions, monitor lease health and schema drift, and never keep cross-project mutable session state.
8. Translate external task states into the canonical job lifecycle. A transport response or process exit is not outcome success; success requires acceptance evidence.
9. Protect costly and destructive operations with idempotency, operation-specific retry classes, and explicit reconciliation.
10. Pause with a bounded handoff package and resume only after lease, checkpoint, project, and evidence revalidation.

Use `runtime.completion_controls.reserve_budget`, `reconcile_budget`, `atomic_work_checkout`, `choose_runtime`, and `transition_job`. No function in this skill grants execution authority by itself.
