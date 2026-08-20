# Lifecycle, workflow, and evidence integrity

- Prove session creation, rotation, expiry, revocation, and cleanup with server timestamps.
- Validate workflow transitions against a state graph; deny skipped, repeated, or unauthorized transitions.
- Hash immutable evidence records and link them to task, policy, implementation version, and postcondition.
- Mark stale, interrupted, missing, or contradicted evidence non-certifying.
- Negative tests: expired session, transition bypass, altered artifact, future timestamp, stale suite.

Lineage: clean-room generalization of reviewed lifecycle patterns.
