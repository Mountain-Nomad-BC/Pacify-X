---
canonical_id: "contractidrewrite"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Contract URI normalization writer

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Rewrites top-level IDs in every contract JSON using relative path.

## Historical source state

Directly rewritten schema files and changed count.

## Limits and unknowns

Does not update references or validate schema corpus; failures can leave partial changes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3799]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
