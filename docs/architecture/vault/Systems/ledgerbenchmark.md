---
canonical_id: "ledgerbenchmark"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Disposable ledger performance benchmark

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Measures live-size copy reads/appends/contention/recovery/rebuild against fixed thresholds.

## Historical source state

Raw samples and budget results.

## Limits and unknowns

Incomplete delta clone and measurement gaps limit benchmark interpretation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3416]] — same-file-bytes

## Directed relationships

- [[Systems/ledgercheckpointreader]] — times copied registry reads (`E1250`)
- [[Systems/ledgerappendplanner]] — measures annotations and thread writers (`E1251`)
- [[Systems/ledgertailrecovery]] — exercises missing-delimiter fallback (`E1252`)
