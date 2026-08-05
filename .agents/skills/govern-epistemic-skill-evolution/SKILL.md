---
name: govern-epistemic-skill-evolution
description: Manage bitemporal and epistemic claims, causal invalidation, retrieval traces, and isolated skill-improvement experiments with independent judging and no live self-editing. Use when facts change over time, derived observations need recomputation, or a skill candidate must be evaluated safely.
---

# Govern Epistemic Skill Evolution

1. Store who holds a claim separately from the claim subject. Record evidence tier, directness, verification, confidence method, citation lineage, world-valid time, and system-known time.
2. Keep managed or remote memory behind the canonical memory interface; it never becomes the authority for truth.
3. Retrieve lexical, semantic, graph, temporal, and policy channels independently, then fuse them with a trace of selected and rejected records.
4. Admit durable memory only when notable. Preserve rejected-source evidence and reasons without promoting low-value mentions.
5. Link observations to the source facts and methods they depend on. When a source changes, invalidate and selectively recompute its transitive dependents.
6. Track typed temporal trajectories and method discontinuities; do not compare incompatible measurements as a smooth trend.
7. Run skill improvement only in an isolated, read-only laboratory. Split lineage-aware train, validation, and untouched held-out cases deterministically.
8. Separate actor, optimizer, and judge identities. Compare baseline and candidate on matched tasks, seeds, models, tools, and budgets.
9. Bound patch size and keep stable skills separate from expiring experimental overlays. A passing self-authored test cannot promote a live skill.
10. Emit proposal-only evidence with improvements, regressions, trigger near misses, routing collisions, rollback, and independent-promotion requirements.

Use `runtime.completion_controls.query_bitemporal_facts`, `invalidate_dependents`, and `evaluate_offline_skill_candidate` alongside the canonical memory and skill-admission owners.
