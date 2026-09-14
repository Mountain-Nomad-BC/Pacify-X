---
canonical_id: "localinference"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Caller-bound llama.cpp HTTP inference

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Uses literal-loopback origin, caller session ID and model digest to send bounded nonstreaming chat request and decode bounded response.

## Historical source state

ProviderResponse with text and nonbillable usage.

## Limits and unknowns

Does not consult lifecycle/resource ledger, authenticate server, or verify returned model identity. Default HTTP redirect handling remains enabled.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2736]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
