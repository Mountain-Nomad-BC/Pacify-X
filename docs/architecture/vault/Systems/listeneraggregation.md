---
canonical_id: "listeneraggregation"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Editor watcher and SCM event aggregation

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Counts edits and aggregates file watcher/SCM notifications.

## Historical source state

Watcher bounded at 256 operation/path keys and 64 scopes per group.

## Limits and unknowns

Editor/SCM trailing debounce can delay indefinitely; disposal drops pending metadata.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S886]] — same-file-bytes
- [[Evidence/S893]] — same-file-bytes

## Directed relationships

- [[Systems/activityattestation]] — hands observed metadata to extension adapter (`E1060`)
