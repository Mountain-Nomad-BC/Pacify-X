---
name: px-work-stop-diagnostics
description: Diagnose why Pacify-X parallel, agent, or cross-IDE work stopped before restarting it. Use when a task stalls, a worker disappears, a claim expires, a budget blocks execution, a provider changes, a worktree moves, a dependency remains incomplete, or a resume packet becomes stale.
---

# PX Work Stop Diagnostics

Trace in this order:

1. Read the current task revision, state, dependencies, blockers, and acceptance evidence.
2. Check worker/node session health and distinguish ephemeral presence from durable execution state.
3. Check claim mode, authority, lease expiry, fencing token, revocation, and overlapping scopes.
4. Check workspace, worktree, branch, dirty/unpushed work, and manual movement/change.
5. Check task/worker/provider/model time, token, cost, and local-resource budgets.
6. Check provider/runtime doctor state, authentication without exposing secrets, model compatibility, and cancellation residue.
7. Check contracts, permissions, effect admission, approvals, evidence, and downstream failures.
8. Verify the resume envelope revision/state hash and reject stale native-session hints.
9. Classify one primary stop reason, identify the unblock owner/action, and release only scopes proven safe to reassign.
10. Record a durable repair receipt and replan dependents. Retry only after the failed boundary changes.

Use the project coordination `diagnoseWorkStop` controller or MCP `pacify_work_stop_diagnostics` when available. Do not poll agents or blindly retry. Never delete dirty worktrees, unpushed branches, evidence, quarantine, or project memory during recovery.
