---
canonical_id: "hostcachecustody"
kind: system
layer: scope
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Retained VS Code cache identity

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Creates/reads a cache ownership marker and resolves platform-specific pinned executable paths.

## Historical source state

Retained-version marker and executable locator.

## Limits and unknowns

Marker and sentinel do not hash executable bytes; creation does not reject linked root; Darwin resolution unsupported.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S526]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
