---
canonical_id: "extensiontestprofiles"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Extension test partition and browser matrix

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Partitions top-level test files and executes unit, performance or required UI browser lanes.

## Historical source state

Child exit status and UI lane matrix receipt.

## Limits and unknowns

No aggregate subprocess timeout; lane selection checks existence only; spawn error can prevent matrix receipt publication.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S786]] — same-file-bytes
- [[Evidence/S1372]] — same-file-bytes
- [[Evidence/S1464]] — same-file-bytes

## Directed relationships

- [[Systems/extensionfixturecontracts]] — includes top-level unit test files (`E1465`)
