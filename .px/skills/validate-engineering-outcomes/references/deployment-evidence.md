# Deployment and evidence validation

- Require focused tests, security review, current evidence, rollback, and explicit approval before deployment.
- Rebuild/retest only affected owners first, then widen by dependency graph.
- Reconcile test counts, artifact hashes, timestamps, implementation versions, and postconditions.
- Keep one heavy validation lane; pause under memory/GPU/process pressure and mark interrupted work non-certifying.
