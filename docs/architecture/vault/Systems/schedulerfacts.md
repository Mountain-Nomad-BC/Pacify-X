---
canonical_id: "schedulerfacts"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# In-memory lane and worker ownership

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Checks caller resource snapshots and lexical path overlaps, stores lane/worker facts.

## Historical source state

Admission and heartbeat snapshots.

## Limits and unknowns

No durable reservation, owner lock, actual resource probe or process-stop proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3000]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
