---
canonical_id: "contextobserve"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Portable Git and provider context

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Collects fixed Git/Codex CLI observations, copies coordination summaries and file references into a hashed portable envelope, and renders handoff instructions.

## Historical source state

Git status/conflict decision, authentication phrase classification, context JSON and prompt.

## Limits and unknowns

Git conflict count is derived after retained-change capping. Token cap and mutation prohibitions are declarations, not enforcement. Named environment-key stripping does not prove absence of every credential channel.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S933]] — same-file-bytes
- [[Evidence/S1380]] — same-file-bytes

## Directed relationships

- [[Systems/coordination]] — copies supplied task claims and handoff references (`E385`)
