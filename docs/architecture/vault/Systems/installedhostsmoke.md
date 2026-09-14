---
canonical_id: "installedhostsmoke"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Installed host listener and Studio smoke driver

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Exercises selected host events and direct installed Studio module paths.

## Historical source state

Host smoke receipt when all required assertions pass.

## Limits and unknowns

Direct module tests differ from editor interaction; optional listener results and cleanup limits remain.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1468]] — same-file-bytes

## Directed relationships

- [[Systems/listenerhealth]] — checks selected actual listener operations (`E1089`)
- [[Systems/studiohostcreate]] — directly calls installed creation coordinator (`E1090`)
- [[Systems/activityreadintegrity]] — checks local activity integrity and operation set (`E1091`)
