---
canonical_id: "environmentrefreshcommand"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Physical extension metadata refresh command

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Collects selected on-disk extension manifests and persists canonical environment discovery.

## Historical source state

Inventory generation, counts and snapshot hash.

## Limits and unknowns

First duplicate ID wins; stat follows manifest links; fixed roots omit other installations; no host activation proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S531]] — same-file-bytes

## Directed relationships

- [[Systems/environment]] — calls persistent discovery (`E1469`)
