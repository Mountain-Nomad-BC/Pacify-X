# Compressed index evaluation

Choose an index from workload evidence: exact versus approximate, raw versus compressed vectors, stable external IDs versus internal slots, filter semantics, similarity mode, initialization, mutation, portability, and persistence requirements.

For every candidate:

1. Freeze dataset, query, embedding, distance, calibration, filter, and authorization fingerprints.
2. Use representative exact-search results as the quality reference.
3. Measure recall at k and forbidden-source exposure before performance.
4. Require explicit calibration state for compressed embeddings and revalidate after distribution drift.
5. Measure cold/warm build, add, search, filtered search, remove, save, and load independently.
6. Verify stable external-ID mapping, deletion/upsert semantics, paired index/metadata generations, corruption handling, and cross-platform fingerprints.
7. Reject a faster candidate when it misses the predeclared recall, authorization, durability, or determinism floor.

Score conventions differ by implementation. Confirm cosine/dot/distance normalization and ordering rather than comparing raw scores across engines.
