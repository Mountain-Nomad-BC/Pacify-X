---
canonical_id: "repairrootgroups"
kind: system
layer: reasoning
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Exact-signature root-cause candidates

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Groups failures sharing identical evidence/owner/dependency tuples.

## Historical source state

Unconfirmed candidate groups.

## Limits and unknowns

Not causal proof or partial-overlap clustering; expected denominator is caller supplied.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2956]] — same-file-bytes

## Directed relationships

- [[Systems/discriminatingplan]] — supplies candidate basis for proposed tests (`E811`)
