---
name: engineer-hybrid-retrieval
description: Design or improve retrieval pipelines that combine dense and lexical retrieval, bounded routing, rank fusion, reranking, active-record hydration, metadata intersection, context assembly, and measurable quality gates. Use when building RAG/search systems or diagnosing corpus, chunking, embedding, ranking, filtering, or citation failures.
---

# Engineer Hybrid Retrieval

1. Establish reviewed queries, expected sources, prohibited sources, latency budgets, and total/eligible denominators.
2. Chunk by source structure and preserve canonical identity, version, provenance, and active-state metadata.
3. Normalize embeddings and use bounded routing or partition selection when full-index search exceeds budgets.
4. Run lexical and dense retrieval independently, preserving ranks and failure states.
5. Fuse ranks with a deterministic method such as reciprocal-rank fusion; tune constants against held-out queries.
6. Rerank only a bounded candidate set and record model/version/latency.
7. Hydrate from the active source of truth, apply strict metadata intersection, and remove deleted, stale, unauthorized, or cross-scope records.
8. Deduplicate and budget final context while preserving claim-to-source traceability.
9. Measure recall, precision, ranking quality, forbidden-source exposure, latency, and regression before activation.

Do not claim that vector search alone proves correctness, access, freshness, or source validity.
