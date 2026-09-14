---
canonical_id: "bundleajv"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Embedded JSON Schema validator engines

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Provides lazy dialect-selected AJV engines and format validation for SDK JSON Schema requests.

## Historical source state

Lazy validator compilation and errors.

## Limits and unknowns

AJV is embedded in an SDK chunk rather than a separate top-level lock entry; this role is distinct from direct PX Zod input parsing.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S802]] — changed-file
- [[Evidence/S804]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
