---
canonical_id: "healthclaimderive"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Canonical health claim derivation

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Derives blocked/stale/degraded/healthy/unknown using registry TTL and supplied facts.

## Historical source state

Seven-domain canonical identity and five-state reports.

## Limits and unknowns

Facts and canonical authority labels are not independent observed proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2238]] — same-file-bytes
- [[Evidence/S2236]] — same-file-bytes

## Directed relationships

- [[Systems/healthreportverify]] — aggregates and validates report (`E971`)
