---
name: admit-capability
description: Review, restrict, quarantine, reject, or admit a reusable skill or runtime capability using provenance, license, dependency, effect, duplication, safety, and test evidence. Use when importing reference material, promoting a candidate skill, updating the capability registry, or deciding whether external tooling may execute.
---

# Admit Capability

1. Treat every candidate as inert reference material until admitted.
2. Map provenance, license, owner, inputs, outputs, effects, dependencies, and canonical overlap.
3. Reject unsafe behavior. Quarantine missing provenance, license review, contract fields, or unknown effects.
4. Restrict untested or high-risk candidates to metadata review or a sandbox.
5. Prefer clean-room implementation or pattern extraction when source tooling is coupled to another product.
6. Validate focused behavior, failure paths, determinism, and registry identity.
7. Promote atomically: contract, implementation, evidence, admission ledger, then active capability map.
8. Re-run `engineering-bootstrap validate`; do not advertise a candidate that fails cross-registry checks.

Read [admission-contract.md](references/admission-contract.md) for dispositions and promotion evidence.
