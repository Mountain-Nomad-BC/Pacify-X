---
name: certify-skeptical-engineering
description: "Evaluate engineering maturity using invalidation-first evidence, discovery denominators, contradictions, unknown classification, and L0-L7 requirements. Use for completion, release, readiness, or certification claims."
---

# Skeptical engineering certification

## Workflow

1. Select the requested L0-L7 maturity level and its evidence classes.
2. Record the current discovery denominator and covered count; never preserve a percentage after the denominator changes.
3. Cross-correlate evidence and explicitly retain contradictory observations.
4. Classify every unknown as expected, unexpected, safe, unsafe, read, mutation, deferred, or blocked.
5. Attempt approved invalidation paths and supersede evidence tied to an older discovery revision.
6. Return `certified` only when all level evidence is current, denominator coverage is complete, and no unknown or contradiction remains.
7. Bind the release claim to the exact source snapshot, dependency locks, generated registries, tests, installed artifact digest, configuration schema, and evidence index with cryptographic hashes.
8. Declare the tools and adapters actually used. A missing, substituted, failed, or unexecuted required tool remains visible in the denominator and cannot be reported as a pass.

## Completion

Apply `contracts/skeptical-certification.schema.json` and `policies/skeptical-certification.json`. A green test run alone is never certification.
