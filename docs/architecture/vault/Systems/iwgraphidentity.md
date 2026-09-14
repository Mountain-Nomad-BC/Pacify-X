---
canonical_id: "iwgraphidentity"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Graph content and saved-view identity

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Hashes node keys and edge endpoint/relation triples across saved-view restart.

## Historical source state

Graph identity and saved-view create/apply/delete flags.

## Limits and unknowns

Labels, weights, attributes and layout are omitted; equal identity does not prove equal weighted graph.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S775]] — same-file-bytes

## Directed relationships

- [[Systems/iwsnapshot]] — uses shared post-offset snapshot mechanisms (`E1586`)
