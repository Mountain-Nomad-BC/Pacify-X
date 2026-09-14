---
canonical_id: "benchmarkroute"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Automatic versus explicit device routing

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Applies CPU-authority, compatibility, VRAM, batching and size gates, then benchmark requirements for automatic GPU routing.

## Historical source state

CPU/CUDA decision with reason and required-check labels.

## Limits and unknowns

Explicit CUDA request bypasses benchmark gate. required_checks lists attempted checks rather than a boolean proof of each; software fingerprint not compared.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2235]] — same-file-bytes
- [[Evidence/S2228]] — same-file-bytes

## Directed relationships

- [[Systems/callbackfallback]] — supplies device and batch decision (`E517`)
