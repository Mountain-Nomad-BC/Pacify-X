---
name: govern-memory-fabric
description: Govern project-scoped factual memory with provenance, confidence, deltas, graph links, compact candidate indexing, correction invalidation, and provider isolation. Use when ingesting, retrieving, repairing, transferring, or certifying memory and derived indexes.
---

# Govern Memory Fabric

## Required sequence

1. Bind the operation to one project, actor, session, and lease.
2. Admit facts, decisions, failures, patterns, preferences, skills, or architectures—not chat transcripts.
3. Require source artifact, evidence locator, source hash, observation/inference status, confidence method, classification, ACL, effective dates, and revision.
4. Use locality signatures only for scoped candidate generation; use semantic reranking for nuance and graph links for deterministic traversal.
5. Store deltas and supersession links. Never silently rewrite history.
6. On correction, invalidate embeddings, graph edges, caches, summaries, and transfer exports, then prove the old claim is no longer retrievable.
7. Treat indexes and external memory providers as rebuildable accelerators; canonical human-readable records remain the source of truth.
8. Make repairs plan-first, dry-run, hash-backed, quarantined, reversible, and approval-gated.

## Operational commands

1. Activate the owning project with `engineering-bootstrap project activate`.
2. Preview and apply bounded project-local sources with `engineering-bootstrap memory ingest`.
3. Pass the owning `--actor-id` and `--session-id` on every memory command; the runtime verifies them against the active lease.
4. Keep new records non-retrievable until independent evidence supports `memory transition --target validated` followed by `--target certified`.
5. Create corrections with `memory correct`. A candidate or merely validated correction cannot suppress certified memory; supersession takes effect only after correction certification.
6. Retrieve through `memory search`; the active lease, workspace binding, project namespace, ACL, lifecycle, supersession, and expiry gates all apply.
7. Inspect and rebuild derived indexes with `memory status` and previewed `memory maintain`; use `memory reconcile` to move invalid generations into recoverable quarantine.
8. Release or switch the project before accessing another namespace.

## Hard boundaries

- No cross-project retrieval or shared private index/process.
- Never convert a backend error into an empty result.
- Never auto-purge stale or duplicate memory.
- Compact addresses are not integrity hashes.
- Candidate memory is not certified memory.

Read [memory contract](references/memory-contract.md) for record and repair rules. Read [provider certification](references/provider-certification.md) before enabling any external memory service.

## Runtime binding

- Controls: `runtime.memory_fabric`, `runtime.memory_vault`, `runtime.workspace_manager`
- Effects: search/status are read-only; ingestion, correction, lifecycle transition, index generation, and reconciliation require an active project lease and explicit approved workspace write
- Activation: metadata-only at startup; load references only for the selected operation

## Completion

Complete only when project-isolation, attribution, backend-error, correction non-influence, index recovery, and deterministic-address tests pass with revision-bound evidence.
