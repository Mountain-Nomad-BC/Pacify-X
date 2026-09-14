---
canonical_id: "exportpublish"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Audit archive and sidecar publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Publishes archive then hash-bound sidecar and attempts owned temporary reclamation.

## Historical source state

Published ZIP and receipt, resource ledger state.

## Limits and unknowns

Two separate replacements; cleanup exceptions/results can be suppressed.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3644]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
