---
canonical_id: "startup"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Bounded startup and lazy skill loading

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Loads compact metadata and limits the active capability working set before hydrating selected bodies.

## Historical source state

Startup snapshot and hydrated working set.

## Limits and unknowns

Availability in a catalog is not execution authorization.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3056]] — changed-file
- [[Evidence/S2322]] — changed-file
- [[Evidence/S2628]] — changed-file
- [[Evidence/S2601]] — same-file-bytes
- [[Evidence/S1502]] — same-file-bytes

## Directed relationships

- [[Systems/catalog]] — loads metadata before bodies (`E021`)
- [[Systems/world]] — loads bounded world-state metadata (`E156`)
- [[Systems/startupconfig]] — loads and validates startup TOML (`E313`)
- [[Systems/lazytransaction]] — hydrates only separately selected capability (`E609`)
