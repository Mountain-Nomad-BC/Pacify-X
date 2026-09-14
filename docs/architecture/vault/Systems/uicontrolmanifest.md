---
canonical_id: "uicontrolmanifest"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Current source control manifest

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Binds declared controls to inventory counts, file hashes and handler metadata.

## Historical source state

Canonical source-control denominator and hash.

## Limits and unknowns

Source existence/hash is separate from semantic handler and installed identity proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S494]] — same-file-bytes

## Directed relationships

- [[Systems/containeduiwalk]] — supplies action-only fixture denominator (`E1085`)
- [[Systems/uicontrolchains]] — supplies exact control denominator (`E1086`)
