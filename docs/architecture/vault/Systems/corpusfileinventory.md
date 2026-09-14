---
canonical_id: "corpusfileinventory"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Hash-backed corpus file inventory

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Walks selected roots and derives file hashes and bounded text structure.

## Historical source state

Sorted records and discovered/record/error accounting.

## Limits and unknowns

Excluded and unreadable directories do not enter a complete physical denominator.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3698]] — same-file-bytes

## Directed relationships

- [[Systems/corpusjsonio]] — uses root parsing canonical serialization and fingerprints (`E1295`)
- [[Systems/corpusexactduplicates]] — provides supplied file hash and size records (`E1302`)
- [[Systems/corpusnearduplicates]] — provides bounded-text fingerprints (`E1303`)
- [[Systems/corpusstructureprojection]] — provides declared text structure (`E1304`)
- [[Systems/corpuspartitionmerge]] — provides sorted partition streams (`E1307`)
- [[Systems/corpuspartitionreport]] — provides partition summary counts (`E1308`)
- [[Systems/historicalsourcejoin]] — supplies inventory hashes and source paths (`E1328`)
- [[Systems/historicalskillidentity]] — supplies skill file identities (`E1329`)
- [[Systems/historicalassetdisposition]] — supplies expected ID denominator (`E1332`)
