---
canonical_id: "assetpaths"
kind: system
layer: release
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Source and installed asset resolution

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Locates source or installed framework assets and maps declared runtime, builder and source-only paths to their distribution layout.

## Historical source state

Resolved path, deliberate no-runtime-wheel path, or rejected relative path.

## Limits and unknowns

declared_file_available accepts a deliberate None for source-only assets; it does not mean those bytes exist in the wheel. resolve_declared_path rejects absolute and parent components, while repository-relative resolution separately checks resolved containment.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2593]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
