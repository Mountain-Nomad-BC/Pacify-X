---
canonical_id: "custody"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Portable release evidence custody

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Builds deterministic evidence ZIP bytes and ordered chunks, binds certificate/subjects and verifies reconstruction sizes and hashes.

## Historical source state

Custody receipt, chunk locators, subject identities and reconstruction digest.

## Limits and unknowns

Hash-correct custody preserves the evidence; it does not independently prove the evidence claims.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2085]] — same-file-bytes
- [[Evidence/S2087]] — same-file-bytes
- [[Evidence/S2920]] — changed-file
- [[Evidence/S2921]] — changed-file
- [[Evidence/S2172]] — same-file-bytes
- [[Evidence/S2095]] — changed-file
- [[Evidence/S2608]] — changed-file
- [[Evidence/S2091]] — changed-file

## Directed relationships

- [[Systems/publicationrestore]] — provides local signed publication entry point (`E494`)
- [[Systems/portableprojection]] — exposes product locator projection (`E495`)
