---
canonical_id: "iwnative"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Native dialog lookup and fallback

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Finds matching dialog text or requests owned native input after observing an outbound operation.

## Historical source state

Dialog click or native helper request.

## Limits and unknowns

Fallback can use request type alone without target, terminal freshness or a visible modal.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S746]] — changed-file
- [[Evidence/S748]] — changed-file

## Directed relationships

- [[Systems/nativeinputclient]] — requests exact labeled native action (`E1569`)
