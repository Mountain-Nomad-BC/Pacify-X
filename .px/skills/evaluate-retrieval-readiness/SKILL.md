---
name: evaluate-retrieval-readiness
description: Measure retrieval coverage, recall at k, reciprocal rank, forbidden-source exposure, source lineage, chunking regressions, and activation readiness. Use when building, changing, rebuilding, or certifying search, semantic retrieval, embeddings, chunkers, rerankers, indexes, knowledge graphs, or grounded-answer pipelines.
---

# Evaluate retrieval readiness

1. Define approved, versioned evaluation cases with relevant and explicitly forbidden source IDs.
2. Keep fixtures synthetic or separately authorized; never place private source bodies in reports.
3. Establish thresholds before observing candidate results.
4. Run `runtime.foundation_assurance.evaluate_retrieval_readiness` on ranked IDs and record coverage, recall at k, mean reciprocal rank, duplicates, and forbidden exposure. For exact, approximate, or compressed index comparisons, run `scripts/evaluate_retrieval_strategy.py --input CASES.json`.
5. Separate failures by corpus, parsing, chunking, metadata, embedding, ranking, filtering, authorization, citation, or freshness layer.
6. Change one layer at a time, rebuild only derived artifacts, and re-run the same versioned suite.
7. Permit activation only when every mandatory threshold passes and forbidden exposure is zero.

Model compressed retrieval as explicit `uninitialized -> initialized -> calibrated -> prepared -> persisted -> loaded -> mutated` states. Require a representative, versioned calibration fingerprint; invalidate readiness when the embedding distribution, distance semantics, dimensions, filtering policy, or persistence generation changes. Benchmark build, add, search, filter, remove, save, and load separately against an exact-search reference, including cold/warm p50/p95/p99 latency, peak memory, serialized size, and deterministic fingerprints.

Read [retrieval evaluation contract](references/retrieval-evaluation-contract.md) before designing fixtures or an activation gate.
Read [compressed index evaluation](references/compressed-index-evaluation.md) when choosing index type, compression, calibration, stable external IDs, filtering, or persistence behavior.

The evaluator does not build indexes, load models, or activate a service. Those effects require separately admitted tools and approval.
