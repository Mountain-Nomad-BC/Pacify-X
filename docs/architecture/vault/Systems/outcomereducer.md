---
canonical_id: "outcomereducer"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Authenticated postcondition reduction

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Combines signed policy and postcondition records against caller-selected local required-check contract.

## Historical source state

Authoritative outcome result after all configured checks.

## Limits and unknowns

Last supplied verified record wins for repeated check names. Contract is not hash-bound to execution evidence here; actor omitted from expected scope.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2592]] — changed-file

## Directed relationships

- [[Systems/signedresolver]] — authenticates policy and check records (`E470`)
