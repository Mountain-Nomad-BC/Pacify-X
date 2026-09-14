---
canonical_id: "generatedcomparison"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Generated projection comparison gate

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Compares source/installed artifacts with canonical owner outputs.

## Historical source state

Per-projection equality checks.

## Limits and unknowns

Generated graph equality does not also require computed graph valid.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2200]] — same-file-bytes

## Directed relationships

- [[Systems/generatedscc]] — compares computed graph to stored JSON (`E652`)
- [[Systems/pythonimportowner]] — rebuilds import inventory for exact comparison (`E653`)
