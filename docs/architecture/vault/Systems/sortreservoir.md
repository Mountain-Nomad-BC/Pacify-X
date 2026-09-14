---
canonical_id: "sortreservoir"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Sort reservoir sampling and type policy

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Checks every source key type and retains seeded record reservoir.

## Historical source state

Full record count and sampled key/ordinal/payload tuples.

## Limits and unknowns

Record count is bounded in memory, but record size, total read time and parser buffer are not.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S104]] — changed-file

## Directed relationships

- [[Systems/sortstreamreader]] — iterates parsed records and coerces keys (`E1349`)
