---
canonical_id: "mcpobservation"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# MCP invocation-based observed status

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Requires a registered definition, an integrity-valid activity ledger and a fresh successful invocation for the exact server version before marking runtime_verified.

## Historical source state

Event ID, observed operation, server version and verification timestamp.

## Limits and unknowns

One matching succeeded event supports the middleware completion predicate, not useful payload content, all routes, present process liveness or exact bundle bytes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1151]] — same-file-bytes
- [[Evidence/S1112]] — changed-file

## Directed relationships

- [[Systems/ui]] — projects invocation-scoped runtime status (`E291`)
