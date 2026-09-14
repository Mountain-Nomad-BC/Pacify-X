---
canonical_id: "models"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Model ranking and attachments

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Ranks model capabilities and binds selected model/provider revisions and fallbacks to an execution plan.

## Historical source state

Model ranking receipt and model attachment.

## Limits and unknowns

Selection, a running model service and actual provider output are distinct states.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2432]] — changed-file
- [[Evidence/S2430]] — changed-file

## Directed relationships

- [[Systems/plan]] — attaches selected model identity (`E025`)
- [[Systems/localmodel]] — describes selected local model route (`E121`)
