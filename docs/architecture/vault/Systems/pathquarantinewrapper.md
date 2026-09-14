---
canonical_id: "pathquarantinewrapper"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Explicit path quarantine wrapper

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Inventories requested paths, calls journaled project quarantine and checks moved inventory before writing wrapper manifest.

## Historical source state

Backend transaction plus separate wrapper manifest.

## Limits and unknowns

Suffix/count heuristic can construct wrong expected-file keys; wrapper failure can follow committed backend move.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3823]] — same-file-bytes

## Directed relationships

- [[Systems/quarantinetxn]] — calls journaled project candidate move (`E772`)
