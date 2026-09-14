---
canonical_id: "walkenginecopy"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Disposable engine copy and partial identity check

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Copies selected current source with exclusions then re-copies and hashes two required files.

## Historical source state

Owned engine copy, file/byte counters and two required digests.

## Limits and unknowns

Whole copied tree is not snapshotted or compared; other files may mix source generations; partial cleanup can mask earlier error.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S608]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
