---
canonical_id: "envcollect"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Environment collection and lexical relationships

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Collects host manifest metadata and fixed local probes, then worker-scanned environment markers and variable names; builds typed resource/contract relationships.

## Historical source state

Full in-memory inventory, ontology and graph with scoped completeness.

## Limits and unknowns

Detected resources are not admitted for invocation. Variable consumers are lexical word matches, and installed/available edges are metadata claims. Missing roots may be filtered before detailed inspection; pruning/depth limits define the scan corpus.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S967]] — same-file-bytes
- [[Evidence/S984]] — same-file-bytes
- [[Evidence/S985]] — same-file-bytes

## Directed relationships

- [[Systems/envstore]] — persists only when requested by caller (`E372`)
