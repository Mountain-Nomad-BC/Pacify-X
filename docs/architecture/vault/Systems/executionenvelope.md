---
canonical_id: "executionenvelope"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Policy evidence and execution envelope

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Resolves signed policy, composes operation owner, checks manifest/effects/budgets and conditionally validates signed effect grant.

## Historical source state

Approved/authoritative/effect_grant_verified/requires_verification fields.

## Limits and unknowns

Only seven named NON_READ_EFFECTS trigger signed grant verification. process/workspace-write aliases skip it. Claims, accepted producer set and manifest are caller input; no action execution.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2133]] — changed-file

## Directed relationships

- [[Systems/operationcompose]] — checks executor ownership after policy resolution (`E465`)
- [[Systems/signedresolver]] — resolves signed policy scope (`E468`)
- [[Systems/granttargets]] — validates grant for seven named effects (`E469`)
