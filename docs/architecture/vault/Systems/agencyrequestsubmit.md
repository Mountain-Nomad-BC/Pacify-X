---
canonical_id: "agencyrequestsubmit"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Agency request to durable create callback

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Calls controller.create with queued agent identity and checkpoint.

## Historical source state

Returned create result; no process launched here.

## Limits and unknowns

No request hash/type/controller identity recheck; capabilities and route hash omitted from handoff.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1513]] — same-file-bytes
- [[Evidence/S1606]] — same-file-bytes

## Directed relationships

- [[Systems/durablepublisher]] — calls create for queued agent record (`E879`)
