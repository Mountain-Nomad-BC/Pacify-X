# Layered memory lifecycle

The canonical owner is `runtime.memory_fabric.MemoryRecord` persisted by `runtime.memory_vault.MemoryVault`. `runtime.memory_intelligence` supplies lifecycle operations around that owner; it is not another store.

## Layers

- L0: immutable sanitized evidence and exact source pointers.
- L1: atomic proposed or certified facts, constraints, decisions, events, failures, and work items.
- L2: scenario indexes and compact summaries rebuilt from L1.
- L3: bounded project doctrine, team model, user core, or agent profile supported by stable reviewed evidence.

## Truth and promotion

`candidate` maps to proposed memory. `validated`, `certified`, and `trusted` are progressively stronger verified states. `disputed`, `expired`, `quarantined`, `revoked`, and `superseded` are non-retrievable. High-impact instructions, constraints, doctrine, and identity models require two independent evidence sources plus explicit human review. An LLM extraction is never independent verification.

## Runtime sequence

1. `sanitize_capture` and `capture_event` produce a hash-bound L0 event. Secret finding output contains codes, never captured secret values.
2. Build a `MemoryRecord` candidate and run `classify_conflict` and `decide_promotion`.
3. Append through `MemoryVault`; use its append-only lifecycle for every promotion, dispute, expiry, revocation, or supersession.
4. Resolve a bounded `MemoryCaller` loadout, then call `rank_memories` with separately produced semantic and graph scores.
5. Call `assemble_context`; L0 remains a pointer and L2 remains a compact index.
6. Use `compact_tool_results` only with a project-local root and `apply=True` after preview. Verify restoration with `restore_offload`.
7. Use `PersistentWriteQueue` for crash-visible pending writes and explicit degraded health.
8. Run `evaluate_memory_retrieval` against positive, forbidden, cross-project, stale, and holdout fixtures.

## Fail-closed rules

- Never cross a project boundary or broaden access when metadata is missing.
- Never retrieve a record outside `certified` or `trusted` states.
- Never allow similarity to override negative matches, revocation, expiry, ACL, or explicit forbidden IDs.
- Never hard-delete evidence or old revisions; quarantine or append a lifecycle transition.
- Never install an external multi-service memory topology as the default. External providers remain derived accelerators and require independent isolation certification.
