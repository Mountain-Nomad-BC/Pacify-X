---
canonical_id: "releasefilteredcopy"
kind: system
layer: release
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Filtered clean-product copy

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Copies tree excluding named generated/evidence and external surfaces.

## Historical source state

Clean directory.

## Limits and unknowns

No intrinsic freeze/receipt/rollback; ordinary copy follows links.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2816]] — same-file-bytes

## Directed relationships

- [[Systems/releaseboundaryaudit]] — caller separately audits resulting copy (`E821`)
- [[Systems/releasefixedsubset]] — standalone script rebuilds disposable copy (`E826`)
