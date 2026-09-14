---
canonical_id: "bundlestdio"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# MCP stdio framing and output backpressure

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Buffers newline-delimited JSON-RPC, dispatches frames and writes serialized replies.

## Historical source state

Validated wire messages and drain/error promises.

## Limits and unknowns

10MiB raw buffer cap is not an in-flight request or output deadline; transport does not attach stdin end/close hooks here.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S800]] — changed-file
- [[Evidence/S812]] — changed-file

## Directed relationships

- [[Systems/bundleera]] — delivers decoded opening messages (`E1616`)
