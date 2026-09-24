---
name: govern-retrieval-generations
description: Build, validate, activate, inspect and roll back coherent retrieval generations while preserving exact canonical IDs, embedding identity, calibration evidence and authorization boundaries.
---

# Govern Retrieval Generations

Use this skill when a retrieval index, embedding revision, TurboVec artifact, reranker configuration or related projection changes. Engineering a retrieval design remains `engineer-hybrid-retrieval`; evaluating its quality remains `evaluate-retrieval-readiness`.

## Sequence

1. Freeze source/corpus revision, embedding identity, chunking/config identity and every artifact digest.
2. Stage a new immutable retrieval generation; never mutate the active generation in place.
3. Validate artifact size/hash/path custody and reject traversal, missing or stale artifacts.
4. Run exact-ID, forbidden-source, recall/ranking, latency and high-severity gates against versioned fixtures.
5. Record validation evidence and its digest.
6. Request activation only after required gates pass and explicit activation authority is supplied.
7. Preserve rollback identity and verify the active generation after publication.
8. Reconcile active artifacts and fail closed on generation/embedding/vector-ID mismatch.

## Boundaries

- Approximate/vector retrieval never becomes canonical identity authority.
- Similarity cannot displace exact evidence.
- Activation and rollback are explicit effects; diagnostics are read-only.
- A rebuilt index is not current until its generation pointer is atomically published by the owning runtime.

## Completion

Return generation identity, artifact manifest, validation receipt, activation/rollback authority state, active generation and all failed gates.
