---
canonical_id: "localagenttools"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Closed deterministic Agent tool worker

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Verifies task signature/body/harness, resolves capability names and runs only sha256, json-keys or bounded delay.

## Historical source state

Progress lines and final completed JSON with objective digest, tool results and model_invoked false.

## Limits and unknowns

No instruction-driven reasoning or model call. Max8 tools; each delay at most1.5sec; no tool calls requires no local-worker capability. Controller and authority owners provide other checks.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1546]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
