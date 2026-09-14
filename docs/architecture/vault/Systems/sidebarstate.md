---
canonical_id: "sidebarstate"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Sidebar progress and render protocol

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Projects task states into weighted reconciled progress and bounded waves, validates host messages, and accepts render acknowledgement only for the current projection revision.

## Historical source state

Weighted numerator/denominator, verifying and complete groups, current revision and render acknowledgement.

## Limits and unknowns

Completed is still verifying; only reconciled contributes to progress. Approved skipped/cancelled tasks leave the denominator. A render acknowledgement is display evidence, not task verification.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1217]] — same-file-bytes
- [[Evidence/S1254]] — same-file-bytes
- [[Evidence/S1215]] — same-file-bytes
- [[Evidence/S1216]] — same-file-bytes

## Directed relationships

- [[Systems/ui]] — acknowledges only the displayed revision (`E287`)
