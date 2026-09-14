---
canonical_id: "sourcearchiveprocess"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Owned Git archive process

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Runs git archive for selected revision under ProcessSupervisor.

## Historical source state

Process receipt, bounded captured streams and tree closure.

## Limits and unknowns

Revision input is not resolved commit identity; worktree-attributes does not archive dirty file bytes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3409]] — same-file-bytes

## Directed relationships

- [[Systems/sourcearchivemembers]] — inspects output only after successful owned tree closure (`E1181`)
- [[Systems/sourcearchiveclosure]] — reconciles workspace on process failures (`E1183`)
