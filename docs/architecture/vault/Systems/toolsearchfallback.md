---
canonical_id: "toolsearchfallback"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Optional rg and Python search corpus

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Searches fixed text via rg or Python os.walk fallback.

## Historical source state

Sorted matched paths.

## Limits and unknowns

Ignore/hidden/binary/symlink behavior differs; output and file bytes unbounded.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3233]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
