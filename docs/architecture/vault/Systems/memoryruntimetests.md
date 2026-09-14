---
canonical_id: "memoryruntimetests"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Memory admission retrieval and persistence fixtures

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Exercises scoped memory selection, structured roundtrip, candidate capture, context offload and retry queue behavior.

## Historical source state

Temporary fixture assertions and supplied retrieval signals.

## Limits and unknowns

No external provider/model operation or crash-after-write exactly-once proof; all tests source-reviewed only.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4257]] — same-file-bytes
- [[Evidence/S4259]] — changed-file
- [[Evidence/S4221]] — same-file-bytes

## Directed relationships

- [[Systems/memorypolicy]] — checks project attribution and lifecycle filters (`E1415`)
- [[Systems/retrievalcore]] — tests six supplied optional score signals (`E1416`)
- [[Systems/hybridadapter]] — defines portable adapter subprocess fixture (`E1417`)
- [[Systems/capture]] — checks capture proposal and promotion decisions (`E1418`)
- [[Systems/recall]] — checks ranking scope and borrowed-agent limits (`E1419`)
- [[Systems/memorycontext]] — checks pointer-only context and offload tampering (`E1420`)
- [[Systems/memorywritequeue]] — retries a callback that first raises (`E1421`)
