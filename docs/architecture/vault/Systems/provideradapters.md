---
canonical_id: "provideradapters"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Local HTTP provider adapters

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Validate literal loopback origin and model/payload, POST bounded JSON with proxies disabled, parse bounded terminal content and usage.

## Historical source state

Ollama generate/chat or llama chat completion and local non-billable usage.

## Limits and unknowns

No live request executed. Missing usage counters can default to zero; requested model identity is not independent server attestation. Gateway observed effects derive from registry mode, not measured socket use.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2718]] — same-file-bytes

## Directed relationships

- [[Systems/localinference]] — implements admitted local adapter class (`E524`)
