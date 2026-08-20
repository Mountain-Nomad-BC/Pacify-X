---
name: certify-reversible-validation
description: Validate UI, authentication, database, migration, or runtime behavior that requires temporary state changes while proving exact restoration afterward. Use for live or semi-live certification where test setup changes protected state and failures, cancellation, or interruption must not leave residue.
---

# Certify Reversible Validation

1. Confirm the target is an authorized test boundary; production requires explicit, specific approval.
2. Capture the exact pre-state and its integrity hash before mutation.
3. Define and test the restoration action before applying the temporary state.
4. Install restoration in `finally`, process-exit, and interruption paths appropriate to the platform.
5. Use generated test identities and values; never embed credentials or copy protected values into logs.
6. Run the narrow validation and preserve its independent evidence.
7. Restore state, read it back, compare hashes/semantic invariants, and fail certification if restoration is unproven.
8. Record both test outcome and restoration outcome. A passing test with failed restoration is a failed campaign.

Prefer disposable snapshots or transactions over direct updates. A cleanup handler is not proof until the restored state is verified.
