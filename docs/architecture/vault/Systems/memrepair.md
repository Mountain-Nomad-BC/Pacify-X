---
canonical_id: "memrepair"
kind: system
layer: memory
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Memory graph remediation planning

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Detects cross-project nodes, missing citations, invalid temporal claims and dependency defects; orders proposed repairs under a spend cap.

## Historical source state

Findings, dependency order, per-step eligibility and plan hash.

## Limits and unknowns

Even apply=true on a step is planning data: top-level mutated=False and authority_granted=False.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2381]] — same-file-bytes

## Directed relationships

- [[Systems/invalidation]] — describes graph repair and reverification (`E162`)
- [[Systems/remediationorder]] — separates dependency order from defect step priority (`E673`)
