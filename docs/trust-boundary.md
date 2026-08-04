# Trust boundary

PACIFY-X distinguishes a caller's claim from an authoritative decision.

A **claim** is any value supplied by the caller, including `valid`, `current`, `policy_allowed`, `tests_passed`, or `executor_claimed_complete`. Claims can be classified for compatibility, but they cannot authorize execution, admit a candidate, or verify an outcome.

**Trusted evidence** is a content-digested record with a detached Ed25519 signature from a signer admitted by `policies/effect-grant-trust.json`. `runtime/trusted_evidence.py` is the shared resolver for outcomes, authorization, and candidate admission. It verifies the record digest, detached signature, signer identity, producer allowlist, age, evidence type, and project/subject/task/execution/actor/session scope. An optional artifact binding verifies the referenced bytes as well.

The three public authority paths use that one model:

- `verify-outcome` resolves a signed policy decision and signed postcondition evidence, then evaluates the required checks from a repository-owned postcondition contract.
- `authorize` resolves a signed, scoped policy decision. Non-read effects additionally require the existing signed effect-grant validator.
- `review-candidate` resolves signed provenance, licensing, test, and security receipts before assigning an admission disposition.

Unresolved, stale, unsigned, incorrectly scoped, hash-mismatched, or unapproved-producer evidence fails closed. A negative evaluation is still a completed evaluation, but it is not authoritative success.

The compatibility commands `evaluate-outcome-claims`, `evaluate-admission-claims`, and `simulate-authorization` are explicitly non-authoritative and cannot promote state.
