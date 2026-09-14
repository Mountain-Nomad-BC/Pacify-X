---
canonical_id: "routingnormalize"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Lexical task normalization and classification

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Retains raw request/constraints and derives domains, classes, terms and metadata lookup confidence.

## Historical source state

Hash-bound task envelope and heuristic classification.

## Limits and unknowns

No negation/semantic constraint enforcement. Classifier matches substrings and defaults unmatched classes to read_only metadata.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1672]] — changed-file
- [[Evidence/S1702]] — same-file-bytes

## Directed relationships

- [[Systems/routingfusion]] — supplies lexical envelope to source ranking (`E500`)
