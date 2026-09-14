---
canonical_id: "historicaltestauthority"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Historical source and candidate evidence tests

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks retained audit dispositions, external migration markers, candidate truth labels and specialty catalog membership.

## Historical source state

Stored-count, status, path-existence and set-equality assertions.

## Limits and unknowns

File existence and internally consistent labels do not independently verify historical source content or delivered semantics.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4203]] — same-file-bytes
- [[Evidence/S4336]] — same-file-bytes
- [[Evidence/S4396]] — same-file-bytes
- [[Evidence/S4400]] — same-file-bytes

## Directed relationships

- [[Systems/specialtymapbuilder]] — checks mapped catalog set identities (`E1410`)
- [[Systems/referenceclaimreconciliation]] — checks retained partial-coverage claims (`E1411`)
