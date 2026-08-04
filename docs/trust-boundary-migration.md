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
