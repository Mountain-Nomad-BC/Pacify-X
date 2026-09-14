---
canonical_id: "rootdiagnosis"
kind: system
layer: reasoning
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Failure grouping and discriminating test plans

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Requires an exact unique failure denominator, groups identical evidence/owner/dependency signatures and proposes removal/substitution tests for possible shared causes.

## Historical source state

Candidate-unconfirmed groups, shared basis, diagnostic hash and test-plan hash.

## Limits and unknowns

Grouping uses exact signatures rather than semantic clustering or causal proof. Plans have repair_authorized=False and execution_primitive=None.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2956]] — same-file-bytes
- [[Evidence/S2955]] — same-file-bytes
- [[Evidence/S4361]] — same-file-bytes

## Directed relationships

- [[Systems/tests]] — proposes causal discriminators without execution (`E273`)
