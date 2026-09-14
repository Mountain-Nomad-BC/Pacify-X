---
canonical_id: "granttargets"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Signed effect grant and concrete target coverage

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Validates exact grant envelope and signature, requested effect subset, project/session/adapter/environment and supplied target inventories.

## Historical source state

Grant validation without nonce consumption or actual execution.

## Limits and unknowns

Same nonce/idempotency can revalidate. Future-issued grant passes if unexpired. Empty host/secret/target inventories skip their conditional checks.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2046]] — changed-file

## Directed relationships

- [[Systems/sshproof]] — runs grant signature verification (`E473`)
