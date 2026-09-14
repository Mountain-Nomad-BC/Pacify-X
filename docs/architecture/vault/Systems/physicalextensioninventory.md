---
canonical_id: "physicalextensioninventory"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Physical extension inventory and loaded state

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Reads sibling package manifests and obsolete markers, merges externally loaded records.

## Historical source state

Fresh synchronous scan on each getter.

## Limits and unknowns

Disk presence and loaded activation are different observations.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1140]] — same-file-bytes

## Directed relationships

- [[Systems/extensionpreviewtokens]] — supplies current target and consumer state (`E1047`)
- [[Systems/extensionconflictsignals]] — supplies extension manifest declarations (`E1048`)
