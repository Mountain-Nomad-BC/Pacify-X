---
canonical_id: "localworker"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Closed deterministic agent harness

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Authenticates a bounded task and dispatches at most eight admitted local tool calls, producing progress and final receipts.

## Historical source state

Task hash, binding identities, sha256/json-keys/delay results and model_invoked=False.

## Limits and unknowns

Receiving an objective does not solve it. This worker reports its presence/hash and runs the explicit closed tool list; host language-model execution is a separate path.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1549]] — same-file-bytes

## Directed relationships

- [[Systems/studioauth]] — resolves capability binding before tool dispatch (`E201`)
