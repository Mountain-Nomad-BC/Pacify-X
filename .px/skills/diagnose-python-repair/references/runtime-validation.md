# Runtime and validation repairs

## Diagnose

- Identify subprocess arguments, shell use, environment inheritance, path trust boundary, and cleanup owner.
- Detect shared mutable test state, order dependence, leaked services, and port/file collisions.
- Separate container process liveness from application readiness.

## Repair

- Use argument arrays, explicit working directories, bounded timeouts, minimal environments, and captured exits.
- Resolve paths beneath an explicit root and reject traversal, symlinks, and ambiguous globs at mutation boundaries.
- Isolate temporary state per test and make teardown idempotent.
- Add container readiness checks that prove required dependencies and app invariants.

## Prove and roll back

- Test traversal, injection, timeout, partial cleanup, randomized order, cold startup, and dependency loss.
- Emit deterministic evidence containing command class, exit status, postconditions, and sanitized artifact hashes.
- Roll back generated files/services through the same explicit ownership boundary.

Lineage: generalized runtime-safety patterns; locally revalidated before use.
