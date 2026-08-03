---
name: verify-outcome
description: Independently verify completion claims against declared postconditions and current, valid, task-scoped evidence. Use after implementation, repair, migration, deployment preparation, or any task where an executor claims success and the result must be proven rather than assumed.
---

# Verify Outcome

1. Extract atomic completion claims and measurable postconditions.
2. Collect evidence records with stable IDs, task scope, kind, source, creation time, sensitivity, and status.
3. Link evidence as support, contradiction, or context. Keep unresolved and contradictory evidence visible.
4. Reject stale, invalid, future-dated, or out-of-scope records as support.
5. Run validation independently of the implementation claim.
6. Mark the result verified only when postconditions pass and current valid evidence exists.
7. Return unsupported claims, failed checks, warnings, and approved evidence IDs for incomplete work.

Read [evidence-contract.md](references/evidence-contract.md) when shaping evidence or deciding freshness.
