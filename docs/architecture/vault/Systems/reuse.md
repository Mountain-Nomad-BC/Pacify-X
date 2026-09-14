---
canonical_id: "reuse"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Measured reuse, decay and revalidation

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Accepts cumulative reuse measurements; weak outcomes can mark the current canonical head suspect and calculate dependency invalidation.

## Historical source state

Reuse history, decay decision, suspect canonical head and revalidation evidence.

## Limits and unknowns

Controller accepts an explicit dependency graph. The inspected Studio measure-reuse dispatcher does not forward graph/revision arguments, so that route falls back to a singleton knowledge node.

## Historical suggested evolution

This loop concretely changes later canonical resolution: suspect knowledge is refused until revalidated.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2292]] — changed-file
- [[Evidence/S2299]] — changed-file

## Directed relationships

- [[Systems/knowledge]] — revokes suspect canonical authority (`E081`)
- [[Systems/invalidation]] — computes dependent stale cone (`E082`)
- [[Systems/revalidation]] — requires explicit evidence-bearing restoration (`E197`)
- [[Systems/dependencycone]] — computes decay cone from supplied or singleton graph (`E648`)
