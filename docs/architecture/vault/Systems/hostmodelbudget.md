---
canonical_id: "hostmodelbudget"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Host model token and cancellation budget

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Selects exact model route, counts conversation tokens and limits output/tool calls with linked cancellation.

## Historical source state

Model output object and token/time accounting.

## Limits and unknowns

Initial selection/token counting precede deadline; full stream is accumulated before output limit; cancellation is cooperative.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1016]] — changed-file

## Directed relationships

- [[Systems/hosttoolinterface]] — offers current registered interfaces (`E1487`)
