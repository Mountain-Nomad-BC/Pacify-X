---
canonical_id: "exacttoolcache"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Exact helper result cache identity and seal

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Keys results by tool/registry/harness/current-process platform and reuses optional cache.

## Historical source state

Persistent or process cache hit.

## Limits and unknowns

Unkeyed seal and incomplete selected-interpreter/dependency identity limit trust.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2105]] — same-file-bytes
- [[Evidence/S2123]] — same-file-bytes
- [[Evidence/S2097]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
