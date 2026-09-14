---
canonical_id: "nativeinputclient"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Native input request and result client

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Writes authenticated sequence requests and polls exact ID/sequence result shape with bounded activation retry.

## Historical source state

Typed sent proof with foreground PID and input count.

## Limits and unknowns

Result file is unsigned and not independently process-attested; key choice is based on label/traversal, not modal semantics.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S525]] — same-file-bytes

## Directed relationships

- [[Systems/nativeinputserver]] — publishes request and polls result (`E1473`)
