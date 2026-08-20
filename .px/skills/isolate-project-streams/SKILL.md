---
name: isolate-project-streams
description: Enforce single-project execution sessions, scoped agent leases, context teardown, and explicit sanitized transfers. Use when starting, switching, pausing, resuming, or coordinating project work, or when checking that memory, tools, prompts, logs, and artifacts cannot cross project boundaries.
---

# Isolate Project Streams

## Required sequence

1. Resolve the workspace, project, agent, session, workstream, lease, intent, and correlation IDs.
2. Reject missing, ambiguous, untagged, or foreign context.
3. Confirm the lease declares roots, tools, expiry, write mode, and side-effect budget.
4. Permit project-local context and immutable universal policy only.
5. For a project switch, require checkpoint, lock and handle release, cache flush, old-lease revocation, root rebinding, and a negative old-project access test.
6. For cross-project reuse, require a sanitized, approved transfer package; import it as destination-owned material.
7. Return a structured allow/deny decision and evidence receipt.

## Operational commands

1. Initialize the bounded workspace with `engineering-bootstrap workspace init`.
2. Admit direct children of `projects/` with `workspace discover`.
3. Inspect the authoritative projection with `workspace status`.
4. Bind exactly one project using `project activate`.
5. For a switch, require `--context-reset-confirmed`; verify the persisted checkpoint, revoked lease, rebound writable root, and negative old-project access receipt.
6. End the writable lease with `project release --context-reset-confirmed`.

## Hard boundaries

- One execution session may have only one writable project lease.
- Project-private memory, embeddings, prompts, logs, source, and agent state never enter global indexes.
- Cross-project access is deny-by-default. Ranking foreign context lower is not isolation.
- Private memory cannot be transferred. Promote only minimal generic capability material.
- The `runtime.workspace_manager` adapter performs approved mutations and snapshots every replaced control projection.

Read [scope contract](references/scope-contract.md) for exact checks and failure behavior.

## Runtime binding

- Controls: `runtime.project_stream_controls`, `runtime.workspace_manager`
- Effects: validation is read-only; initialization, discovery, activation, switching, and release require explicit approved workspace writes
- Activation: metadata-only at startup; load this body only after selection

## Completion

Complete only after boundary tests prove foreign read, write, prompt/log exposure, and stale cache access are denied. A positive happy-path test is insufficient.
