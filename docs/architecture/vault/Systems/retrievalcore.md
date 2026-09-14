---
canonical_id: "retrievalcore"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Hybrid retrieval policy kernel

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Filters caller-supplied sources by identity visibility, combines lexical and available optional signals and enforces result/context-byte budgets.

## Historical source state

Cited hits, per-signal contribution and availability, owner revision and retrieval trace.

## Limits and unknowns

The located portable corpus adapter calls this kernel. Memory Vault and repository-map rankers have distinct entry points. Dense scores remain caller-supplied.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2991]] — same-file-bytes
- [[Evidence/S2990]] — same-file-bytes

## Directed relationships

- [[Systems/retrievalproof]] — provides ranked results for evaluation (`E196`)
