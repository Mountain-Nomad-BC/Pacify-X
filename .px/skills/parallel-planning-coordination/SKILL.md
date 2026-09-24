---
name: parallel-planning-coordination
description: Coordinate dependency-safe work across IDEs and agents through durable task graphs, bounded claims, leases, receipts, reconciliation, and layered memory.
---

# Parallel Planning Coordination

Use this skill when two or more agents, IDEs, or execution harnesses may work on one project concurrently.

1. Bind every participant to one project, stable actor, harness, session, and accountable owner.
2. Convert the objective into a dependency DAG with immutable acceptance criteria.
3. Declare file, directory, symbol, service, and resource claims before dispatch.
4. Reject unordered tasks whose ancestor/child scopes overlap.
5. Claim only dependency-ready work through an atomic bounded lease.
6. Keep Git authoritative. A task claim grants no commit, merge, reset, checkout, clean, fetch, pull, or push authority.
7. Append progress, failure, evidence, and exact-next-action receipts.
8. Mark work complete only after acceptance evidence exists; reconcile before releasing the claim.
9. Update memory through the ladder: session observation → project candidate → verified state → system candidate.
10. Never auto-promote a system-memory candidate or treat TurboVec/vector output as authority.

The canonical operational artifacts are .engineering-bootstrap/coordination/state.json,
events.jsonl, handoff.json, HANDOFF.md, receipts/, and memory/.

Read/write access is exposed through the Pacify-X extension UI and narrow MCP tools.
Every write tool declares its effect and returns a hash-linked receipt.

