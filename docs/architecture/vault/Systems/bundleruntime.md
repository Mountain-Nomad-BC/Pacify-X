---
canonical_id: "bundleruntime"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Generated CommonJS and ESM runtime

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Lazily initializes CommonJS modules and projects exports through generated getters.

## Historical source state

Cached modules and import aliases.

## Limits and unknowns

Bundling changes module filesystem context; source syntax parity does not prove identical relative asset resolution.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S788]] — changed-file
- [[Evidence/S836]] — changed-file

## Directed relationships

- [[Systems/bundleworkerpaths]] — changes runtime module directory (`E1614`)
