---
canonical_id: "ollamacatalog"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Local Ollama model catalog adapter

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Fetches loopback tags and publishes model metadata to VS Code.

## Historical source state

Host-visible catalog with fixed input/output capacities.

## Limits and unknowns

No actual context-window measurement, catalogue count cap or body size cap.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1153]] — same-file-bytes

## Directed relationships

- [[Systems/ollamastream]] — offers model identity for requested chat (`E1075`)
