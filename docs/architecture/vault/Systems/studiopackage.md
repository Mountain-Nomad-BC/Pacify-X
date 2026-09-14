---
canonical_id: "studiopackage"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Studio editor package materialization

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Materializes normalized editor files into a digest-addressed project tree, records lifecycle custody, verifies reuse and reclaims only against matching durable draft evidence.

## Historical source state

Materialization inventory, registered/closed receipts, retained uncertain state and reclamation receipt.

## Limits and unknowns

Files are written individually to the target; published is a verified lifecycle state, not a directory-wide atomic rename. Uncertain failures retain evidence. This staging tree is distinct from canonical Studio revision publication.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1317]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
