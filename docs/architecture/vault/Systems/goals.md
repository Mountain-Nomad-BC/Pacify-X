---
canonical_id: "goals"
kind: system
layer: scope
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Durable goal transition semantics

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Computes legal goal transitions, project/session ownership, continuation spending and evidence-required completion.

## Historical source state

Next-state object, history, acceptance evidence and state hash.

## Limits and unknowns

Function is side-effect-free. Persistence and recurring observation capture belong to an external owner; blocked history must already contain the required observations.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2045]] — same-file-bytes
- [[Evidence/S2044]] — same-file-bytes

## Directed relationships

- [[Systems/goaltransitionmetadata]] — exposes nonpersistent transition utility (`E774`)
- [[Systems/specificationclosure]] — exposes stage closure utility (`E775`)
