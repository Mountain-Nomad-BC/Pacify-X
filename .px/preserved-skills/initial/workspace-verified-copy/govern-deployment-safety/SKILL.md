---
name: govern-deployment-safety
description: Certify release hygiene, environment contracts, migration state, persistence across restart, artifact identity, health, rollback, and cryptographic evidence before deployment. Use when declaring an application or package production-ready, promoting images, applying migrations, or validating a deployment candidate.
---

# Govern Deployment Safety

1. Freeze source revision, build inputs, dependency locks, migration head, configuration schema, and target environment.
2. Scan the release context for secrets, caches, test residue, local state, backups, and excluded files.
3. Compare required/declared/runtime environment keys without exposing values.
4. Prove one migration head, upgrade on a disposable target, downgrade when supported, interrupted recovery, and persistence across controlled restart.
5. Build once; record artifact/image identities and deploy the exact recorded artifact.
6. Verify health, readiness, critical consumer contracts, and rollback using the deployed identity.
7. Bind claims to source bundle digest, revision, migration, artifact, environment, and evidence hashes.
8. Report residual risks and all unexecuted gates. A described drill is not an executed drill.

For paired binary and metadata artifacts, validate metadata before writing, write temporary generations on the destination filesystem, flush and sync as supported, atomically replace each destination, and bind both files to one generation fingerprint. Detect mixed generations, stale sidecars, duplicate or rewound ID watermarks, unknown schema versions, truncation, hostile allocation lengths, and bounded transient replacement retries. Cleanup failure must never mask the primary failure, and original artifacts remain recoverable until the new generation is verified.
