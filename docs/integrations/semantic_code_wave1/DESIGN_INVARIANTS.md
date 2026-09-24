# Wave 1 Design Invariants

1. **Evidence before action.** Source is acquired into an immutable SHA-256 snapshot before analysis or edit planning.
2. **No implicit writes.** Query, indexing, diagnostics, edit planning and preview do not modify the target project.
3. **Explicit mutation grant.** `SemanticCodeService` defaults to `allow_writes=False`; a write request otherwise fails closed.
4. **Revision-bound edits.** Every edit plan binds to the exact source SHA-256 it was planned against.
5. **Recheck at commit.** A write re-reads the source under a PX `FileLock` and checks revision again immediately before replacement.
6. **Validate before replace.** The candidate document is parsed by the selected semantic backend before a write can commit.
7. **Atomic single-file commit.** Candidate bytes are written to a same-directory temp file, fsynced and atomically replaced.
8. **Project containment.** Absolute paths, `..` traversal and resolved paths outside the project root are rejected.
9. **Bound acquisition before ranking.** File, byte, symbol, reference, graph, result and wall-clock budgets are explicit and finite.
10. **Conservative references.** Ambiguity remains ambiguity. Wave 1 does not pretend an AST name guess is equivalent to type-aware LSP resolution.
11. **Backend-neutral callers.** Consumers depend on PX semantic contracts, not Python AST or any future LSP implementation.
12. **Project state isolation.** Sessions are keyed by canonical project root and never switch process-global active-project state.
13. **Session authority cannot drift.** An existing session cannot be silently reopened with different write authority, limits, or backend registry.
14. **Derived evidence stays derived.** Exported semantic indexes are labeled `derived_non_authoritative`.
15. **Deterministic receipts.** Client-facing semantic reads and mutation attempts carry deterministic receipts; wall-clock time is omitted by default so identical evidence yields identical digests.
16. **Models are callers, never authorities.** A local model may request semantic operations only through later PX orchestration/effect contracts. Model output does not itself authorize reads, writes, registry changes, memory promotion, graph authority, or release-state changes.
17. **No release-authority mutation in this wave.** No generated-artifact authority, source inventory, certification denominator, Atlas authority, skill authority, provider authority, memory authority, or release manifest is edited by the package itself.
