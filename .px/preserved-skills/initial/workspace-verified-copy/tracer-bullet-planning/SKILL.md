---
name: tracer-bullet-planning
description: Break work into vertical, independently verifiable slices with explicit blocking edges.
---

# Tracer-Bullet Planning

Create narrow end-to-end slices, not layer-by-layer chores.

Each ticket must:
- deliver observable behavior through every required layer;
- fit one fresh execution context;
- declare acceptance evidence;
- declare blockers by stable identity;
- remain green or explicitly belong to an integration branch.

For wide mechanical changes use expand → migrate batches → contract. Never force a repository-wide rename into fake vertical slices.

Emit a DAG, validate it is acyclic, and identify the current frontier: all open tickets whose blockers are complete.

Before declaring delivery complete, use `runtime.durable_state.close_specification_lifecycle` to connect principles, specification, clarification, design, tasks, implementation evidence, and acceptance. Reject missing stages, forward or unresolved dependencies, tasks without evidence, and acceptance that did not pass.
