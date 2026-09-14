---
canonical_id: "scannerprocess"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Scanner identity version and execution

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Checks absolute executable path and explicit network policy, then runs version and scanner with minimal environment.

## Historical source state

Exit/JSON parse status, output hash and executable hash.

## Limits and unknowns

Isolation is caller flag; hashes after execution, unbounded capture, no owned process-tree wrapper.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3227]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
