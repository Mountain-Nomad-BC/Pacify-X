---
canonical_id: "summarycursor"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Session summary cursor and namespace

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Selects distinct initial sentences while advancing to the last pending event.

## Historical source state

Numbered checkpoint/final JSON with full pending-range hash.

## Limits and unknowns

Fact truncation still consumes all pending events; sanitized session names can collide or retain dot path segments.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2373]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
