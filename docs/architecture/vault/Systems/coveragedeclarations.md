---
canonical_id: "coveragedeclarations"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Source requirement ownership checks

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks declared control IDs/states, required operational labels, owner/contract/test path availability and active/admitted skill references.

## Historical source state

Control count, missing references and lifecycle consistency errors.

## Limits and unknowns

This function does not execute referenced tests or independently establish that an operational label is true.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3053]] — same-file-bytes
- [[Evidence/S1653]] — changed-file
- [[Evidence/S2802]] — changed-file
- [[Evidence/S2778]] — changed-file

## Directed relationships

- [[Systems/admission]] — checks declared control-to-skill eligibility (`E239`)
