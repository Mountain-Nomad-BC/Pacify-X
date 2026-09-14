---
canonical_id: "teampack"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Team package candidate staging

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Inventories a bounded team package and stages selected metadata with collision handling and an import receipt.

## Historical source state

Source manifest hash, candidate-only entities and import receipt under coordination/imports.

## Limits and unknowns

Stages selected metadata in a new candidate receipt, not package source bodies. MCP re-inventories before staging; the low-level API validates supplied preview markers/hash shape. Missing license is a warning and collisions use caller IDs.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1329]] — same-file-bytes
- [[Evidence/S1328]] — same-file-bytes
- [[Evidence/S857]] — same-file-bytes
- [[Evidence/S1332]] — same-file-bytes

## Directed relationships

- [[Systems/admission]] — requires provenance and admission review (`E221`)
