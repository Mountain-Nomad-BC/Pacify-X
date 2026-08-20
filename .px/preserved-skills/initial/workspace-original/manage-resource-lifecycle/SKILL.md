---
name: manage-resource-lifecycle
description: Classify, register, retain, reconcile, and safely reclaim PACIFY-X-owned workspaces and process trees with fail-closed path, evidence, quarantine, recovery, budget, and receipt controls. Use when tests, scans, builds, temporary environments, staging, certification, cancellation, restart recovery, cleanup, storage pressure, or quarantine disposition create resources that must not leak or be deleted unsafely.
---

# Manage Resource Lifecycle

Use `runtime.resource_lifecycle` as the sole runtime owner. Read
`references/lifecycle-policy.md` before authorizing reclamation, process-tree
termination, quarantine disposition, or run closure.

## Workflow

1. Identify the project, run, lane, creator, purpose, expected cleanup event, and
   allowed cleanup root.
2. Classify every resource as `protected`, `evidence`, `quarantine`, `ephemeral`,
   or `unknown`. Retain on ambiguity.
3. Register owned paths and processes when created; do not infer ownership from a
   name, age, size, executable, or location.
4. Promote required outputs and evidence outside disposable workspaces, then
   validate their presence and readability.
5. Mark the owning run `completed`, `failed`, `cancelled`, `abandoned`, or
   `recoverable`. Preserve recoverable resources.
6. Evaluate the safe reclamation gate. Treat every failed or unknown check as a
   retain decision.
7. Run one conservative cleanup worker by default, refuse link/reparse ambiguity,
   verify the target is absent, and write a cleanup receipt.
8. Reconcile active processes, unexplained ephemerals, quarantine, evidence,
   cleanup failures, and receipts before certifying run closure.

## Runtime interface

- Inspect: `python -m runtime.cli resources status --ledger <path>`
- Dry-run recovery: `python -m runtime.cli resources reconcile --ledger <path>`
- Apply eligible cleanup: add `--apply` only after declared authority exists.
- Create managed workspaces with `ResourceManager.workspace(...)`.
- Launch cancellable workers with `ResourceManager.spawn_owned_process(...)`.

## Boundaries

- Never auto-delete protected, evidence, external, unknown, or unreviewed
  quarantine data.
- Never crawl a whole machine during normal startup; reconcile from the ledger.
- Never kill a process by executable name. Terminate only the live handle whose
  registered identity remains provable.
- Never certify functional success while resource reconciliation fails.
