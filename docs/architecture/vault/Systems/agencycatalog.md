---
canonical_id: "agencycatalog"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Agency specialist registry and declared graph

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Validates body/manifest identities and derives agent/division/capability/handoff graph.

## Historical source state

Metadata corpus and deterministic projection.

## Limits and unknowns

Declared handoffs are references, not executed transfers.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1559]] — changed-file
- [[Evidence/S1552]] — changed-file

## Directed relationships

- [[Systems/agencyranking]] — supplies lifecycle and routing metadata (`E935`)
- [[Systems/agencyhydration]] — binds selected body and manifest bytes (`E939`)
