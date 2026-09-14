---
canonical_id: "observercapture"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Observer bounded metadata capture

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks active consent, expiry, metadata shape, count/byte limits and drop deltas.

## Historical source state

Returned observation batch and cumulative counters.

## Limits and unknowns

Budgets bound accepted records; no independent timer or guaranteed bounded decoder work.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2577]] — changed-file
- [[Evidence/S2581]] — changed-file

## Directed relationships

- [[Systems/observershutdown]] — checks expiry before capture (`E964`)
- [[Systems/observeroutbox]] — commits counters and canonical event (`E965`)
