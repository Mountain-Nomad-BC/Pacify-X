---
canonical_id: "strategymodes"
kind: system
layer: reasoning
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Reasoning mode dependency plan

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Scores goal tokens and expands selected modes through fixed dependencies.

## Historical source state

Ordered mode labels and generic stop conditions.

## Limits and unknowns

No handler execution; required modes can be truncated and expanded plan can exceed max_modes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1914]] — same-file-bytes

## Directed relationships

- [[Systems/constraintsearch]] — names a constraint prerequisite without invoking it (`E710`)
