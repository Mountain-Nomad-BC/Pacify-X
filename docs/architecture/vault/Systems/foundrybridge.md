---
canonical_id: "foundrybridge"
kind: system
layer: acquisition
currentness: changed-file
runtime_observed: false
certified: false
---
# Foundry-to-Studio candidate bridge

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Validates candidate lineage and returns explicit accept/reject intake as a typed Studio draft object.

## Historical source state

Candidate export, unkeyed lineage digest and in-memory SkillStudioDraft object.

## Limits and unknowns

Intake does not persist or stage a physical draft; conversion to the normal package lifecycle requires another caller.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2188]] — changed-file
- [[Evidence/S3040]] — changed-file

## Directed relationships

- [[Systems/skillstudio]] — creates accepted or rejected draft (`E065`)
