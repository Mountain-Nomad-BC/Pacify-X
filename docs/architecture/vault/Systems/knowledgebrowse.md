---
canonical_id: "knowledgebrowse"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Knowledge catalog and history projection

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Reads signed proposal/canonical heads, enumerates bounded rollback targets and learning states, and projects authority flags for browsing.

## Historical source state

Signed head metadata, rollback targets, projected authoritative/revalidation fields and learning browse result.

## Limits and unknowns

Browsing canonical history is a real consumer distinct from resolve_canonical. The latter returns signed revision bytes and can reject suspect authority; neither proves universal injection into agents.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2288]] — changed-file
- [[Evidence/S2298]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
