---
canonical_id: "depthproxy"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Public interface AST depth proxy

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Counts public interface arguments/members and AST implementation nodes from contained Python source.

## Historical source state

Per-symbol depth proxy and explicit metric boundary.

## Limits and unknowns

No proof of encapsulation or design quality; private/dunder methods excluded and whole source parsed without size cap.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2671]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
