# Trust-boundary compatibility and migration

The former public interfaces accepted caller-supplied truth fields. They are now separated from authority:

| Previous use | Current interface | Authority |
|---|---|---|
| `verify-outcome` with inline postconditions and Boolean evidence | `evaluate-outcome-claims --request <file>` | Non-authoritative |
| `review-candidate` with provenance/test/license Booleans | `evaluate-admission-claims --manifest <file> --evidence <file>` | Non-authoritative |
| `authorize --policy-allowed` | `simulate-authorization --policy-allowed ...` | Non-authoritative |
| Outcome verification | `verify-outcome --request <trusted-request>` | Signed evidence required |
| Candidate admission | `review-candidate --manifest <file> --evidence <trusted-request>` | Signed receipts required |
| Operational authorization | `authorize --request <trusted-request>` | Signed policy required; effect grant for writes |

Automation must use the documented exit codes rather than treating successful JSON parsing as admission or verification. Rejection and quarantine are intentionally nonzero. Claim-only compatibility commands return zero when the evaluation itself completes, while their JSON always contains `authoritative: false`.

The request and record schemas are `contracts/outcome-verification-request.schema.json`, `contracts/candidate-admission-request.schema.json`, `contracts/authorization-request.schema.json`, and `contracts/trusted-evidence-record.schema.json`.

## Signing authority for evidence producers

Each trusted signer must explicitly declare an `evidence_producers` object mapping producer identities to allowed evidence types. For example, `"evidence_producers": {"security-reviewer": ["security"]}` grants that signer only that producer/type pair. A request's producer allowlist can narrow these grants; it cannot create them. A signer without this configuration cannot authenticate trusted evidence. Existing effect-grant or release trust does not implicitly grant an evidence role. Production grants must follow the owning authority's admission process; test fixture grants are not production policy.

The shared resolver requires an actual bounded record, a filename/reference identity matching its signed identity, explicit Boolean assessments, and original contained regular-file paths. Security evidence must explicitly contain `malicious_or_unsafe: false` to establish a negative assessment; an absent or malformed flag is invalid. Transfer evidence supports `transfer_sanitization`, `human_approval`, `destination_ownership`, and `transfer_tests`, with both source and destination project identities and an explicit `accepted` Boolean.

Limits are 1 MiB per record or trust policy, 64 KiB per detached signature, 64 MiB per optional artifact, 64 accepted producers and a positive age budget of at most 365 days. Artifacts are acquired only after record authentication and applicability checks. The record digest and SSH signature encoding remain unchanged. These bounds do not establish multi-file snapshot isolation, native child ownership, replay protection, current-clock freshness, or complete subject provenance; those require their respective owners' evidence.
