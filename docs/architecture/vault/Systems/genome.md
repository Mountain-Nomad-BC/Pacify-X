---
canonical_id: "genome"
kind: system
layer: reasoning
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Capability dependency and mutation analysis

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Builds a typed capability graph, detects duplicates by weighted semantic overlap, checks dependency health and proposes missing-output mutations.

## Historical source state

Capability genome, cycle/orphan diagnostics and proposal-only mutation plan.

## Limits and unknowns

Missing outputs produce validation-bound proposals, not new executable capabilities.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2407]] — same-file-bytes

## Directed relationships

- [[Systems/improvement]] — proposes missing capability outputs (`E148`)
