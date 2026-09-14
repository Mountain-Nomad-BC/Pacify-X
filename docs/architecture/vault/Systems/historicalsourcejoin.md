---
canonical_id: "historicalsourcejoin"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Historical hash and current owner reconciliation

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Joins inventory hashes to historical dispositions, current paths and first matching rules.

## Historical source state

Disposition rows with current owner hashes.

## Limits and unknowns

A same-path changed file is automatically superseded; historical hash matches take precedence.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S091]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
