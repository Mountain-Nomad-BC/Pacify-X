---
canonical_id: "nativemigration"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# First native skill custody migration

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Snapshots and copies originals, prepares packages, relocates source and publishes index/projection.

## Historical source state

Phase journal, original/verified backups and native packages.

## Limits and unknowns

First journal follows backup copies; partial preparation and resume windows remain.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3744]] — same-file-bytes

## Directed relationships

- [[Systems/nativebackupcustody]] — copies and verifies permanent originals (`E885`)
- [[Systems/nativeindexidentity]] — builds index after package publication (`E886`)
- [[Systems/nativepackaging]] — regenerates pyproject before committed journal (`E887`)
