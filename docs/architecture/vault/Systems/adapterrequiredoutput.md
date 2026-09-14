---
canonical_id: "adapterrequiredoutput"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Adapter mapping and required output

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Maps exact declared field types and transforms source record.

## Historical source state

Shallow result dictionary.

## Limits and unknowns

Optional source can map to required target and then be absent from output.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S246]] — same-file-bytes
- [[Evidence/S248]] — same-file-bytes

## Directed relationships

- [[Systems/proposalidentity]] — can separately propose adapter metadata (`E781`)
