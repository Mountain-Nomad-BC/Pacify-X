---
canonical_id: "observernative"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Native observer lifecycle backend

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Starts/stops Windows ETW or exact Linux Audit rule using non-shell runner.

## Historical source state

Native collector control when explicitly called.

## Limits and unknowns

Decoding requires metadata callback; macOS unsupported. Active flag is process memory.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2563]] — changed-file
- [[Evidence/S2568]] — changed-file

## Directed relationships

- [[Systems/observercapture]] — returns injected metadata source records (`E963`)
