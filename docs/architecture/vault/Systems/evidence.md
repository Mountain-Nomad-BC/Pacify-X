---
canonical_id: "evidence"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Evidence assembly and claim support

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Links typed evidence to claims while tracking freshness, sensitivity, contradiction and unsupported claims.

## Historical source state

EvidencePackage, supported/unsupported claims and evidence links.

## Limits and unknowns

A source hash proves identity; it does not by itself prove the claimed behavior.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2076]] — changed-file

## Directed relationships

- [[Systems/verify]] — supplies claim-linked evidence (`E095`)
- [[Systems/rootdiagnosis]] — supplies complete failure set for grouping (`E272`)
- [[Systems/claimassembly]] — provides pure claim support assembly (`E478`)
- [[Systems/externalmanifest]] — validates externalized inventory identities (`E496`)
- [[Systems/featureclaims]] — compares declared feature acceptance classes (`E497`)
