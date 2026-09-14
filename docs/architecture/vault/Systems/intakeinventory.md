---
canonical_id: "intakeinventory"
kind: system
layer: scope
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Existing-project inventory and candidate discovery

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Walks excluded tree and hashes selected files while classifying names into language/test/CI candidates.

## Historical source state

Inventory digest, candidate lists and gaps.

## Limits and unknowns

Filename heuristics; walked sizes precede whole-file reads and overflow beyond one extra file raises.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2251]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
