---
canonical_id: "syntaxcanonicalidentity"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# JSON YAML and AST canonical identity

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Hashes normalized parsed representation while retaining original byte identity.

## Historical source state

Effective revision and canonicalizer labels.

## Limits and unknowns

Normalization is not general behavioral equivalence; canonicalizer/version not included in digest.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3019]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
