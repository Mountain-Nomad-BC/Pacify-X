---
name: supervise-contained-execution
description: "Authorize, block, or escalate a proposed action against declared effects, owned paths, resource budgets, policy, and human approvals. Use before installations, network access, services, migrations, destructive operations, load tests, chaos, or red-team activity."
---

# Contained execution supervision

## Workflow

1. Require a typed action matching `contracts/containment-action.schema.json`.
2. Compare requested effects with allowed effects, targets with owned paths, and requested budgets with limits.
3. Require explicit approval for every mutating or elevated effect.
4. Block scope escape, undeclared effects, excess budgets, missing approval, and any attempt by the executor to override policy.
5. Emit a deterministic allow/block/escalate result and audit-record hash before execution.

## Completion

The supervisor never executes the action it evaluates and never self-approves. Unresolved scope, effect, ownership, or policy state fails closed.
