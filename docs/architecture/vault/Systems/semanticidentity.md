---
canonical_id: "semanticidentity"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Byte and syntax-normalized identity

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Retains a byte hash and optionally hashes canonical JSON/YAML or Python AST structure, with a versioned canonicalizer.

## Historical source state

Byte, semantic and effective revisions plus canonicalizer identity.

## Limits and unknowns

Syntax normalization is not proof of behavioral equivalence. Unsupported formats use byte identity; invalid supported formats raise rather than silently downgrade. A production caller was not established in the searched surfaces; this node is deliberately shown without a behavioral edge.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3018]] — same-file-bytes

## Directed relationships

- [[Systems/syntaxcanonicalidentity]] — implements supported-format normalization (`E814`)
