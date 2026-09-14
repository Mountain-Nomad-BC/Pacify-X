---
canonical_id: "ledgercheckpointreader"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Optimistic ledger checkpoint reader

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Verifies head, ledger fingerprint and tail; optionally validates snapshot/delta; rereads head.

## Historical source state

Bounded retry coherent checkpoint or explicit unavailable error.

## Limits and unknowns

Compact read does not open snapshot; fingerprint cache trusts filesystem identity tuple.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2501]] — changed-file
- [[Evidence/S2504]] — changed-file

## Directed relationships

- [[Systems/ledgerstatereducer]] — reduces optional delta over sealed base (`E1241`)
- [[Systems/dashboard]] — serves head for default cards and snapshot for details (`E1246`)
- [[Systems/reviewedcardbindings]] — provides current controls and existing scope (`E1261`)
- [[Systems/aggregatesplitplanner]] — provides selector gap links and current cards (`E1262`)
- [[Systems/cardqualityannotation]] — provides current annotations to repair (`E1263`)
- [[Systems/controlinventoryreconcile]] — provides current declared denominator (`E1272`)
- [[Systems/controlcompletenesscheck]] — provides dispositions and bound card states (`E1279`)
