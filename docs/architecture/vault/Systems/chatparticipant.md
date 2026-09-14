---
canonical_id: "chatparticipant"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# VS Code chat participant and deterministic views

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Provides status/context/skills views or invokes the model selected by chat host.

## Historical source state

Streamed response and activity observations.

## Limits and unknowns

Uses host-provided model without Studio route/budget loop; local timeout/output cap are absent.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S993]] — changed-file

## Directed relationships

- [[Systems/extensioncontextcache]] — builds bounded evidence envelope (`E1502`)
