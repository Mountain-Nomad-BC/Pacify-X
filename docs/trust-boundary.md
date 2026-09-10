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

## Signing authority for evidence producers

Each trusted signer must explicitly declare an `evidence_producers` object mapping producer identities to allowed evidence types. For example, `"evidence_producers": {"security-reviewer": ["security"]}` grants that signer only that producer/type pair. A request's producer allowlist can narrow these grants; it cannot create them. A signer without this configuration cannot authenticate trusted evidence. Existing effect-grant or release trust does not implicitly grant an evidence role. Production grants must follow the owning authority's admission process; test fixture grants are not production policy.

The shared resolver requires an actual bounded record, a filename/reference identity matching its signed identity, explicit Boolean assessments, and original contained regular-file paths. Security evidence must explicitly contain `malicious_or_unsafe: false` to establish a negative assessment; an absent or malformed flag is invalid. Transfer evidence supports `transfer_sanitization`, `human_approval`, `destination_ownership`, and `transfer_tests`, with both source and destination project identities and an explicit `accepted` Boolean.

Limits are 1 MiB per record or trust policy, 64 KiB per detached signature, 64 MiB per optional artifact, 64 accepted producers and a positive age budget of at most 365 days. Artifacts are acquired only after record authentication and applicability checks. The record digest and SSH signature encoding remain unchanged. These bounds do not establish multi-file snapshot isolation, native child ownership, replay protection, current-clock freshness, or complete subject provenance; those require their respective owners' evidence.
