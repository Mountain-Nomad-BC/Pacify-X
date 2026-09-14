---
canonical_id: "localreadiness"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Local server health and lifecycle publication

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Polls HTTP health after spawn and appends started or failed-start event; status projects last event plus custody record.

## Historical source state

Hash-chained events and separately replaced head.

## Limits and unknowns

Health has no socket-to-child/model binding; callback or started publication exceptions can bypass cleanup. Readiness timeout does not include spawn.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2345]] — changed-file
- [[Evidence/S2338]] — changed-file
- [[Evidence/S2346]] — changed-file

## Directed relationships

- [[Systems/localclosure]] — provides session identity and durable status (`E522`)
- [[Systems/localinference]] — requires explicit caller transfer of origin session and digest (`E525`)
