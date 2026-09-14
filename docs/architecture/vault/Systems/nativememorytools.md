---
canonical_id: "nativememorytools"
kind: system
layer: memory
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Native memory and retrieval helper tools

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Provides separate candidate checks, scope-filtered JSON storage, supplied-item context packing, supplied-result evaluation and metric drift comparison.

## Historical source state

Caller-supplied verification/scopes/scores, simple JSON records and analytical decisions.

## Limits and unknowns

The store does not invoke the separate write-gate script. Scope is caller supplied, not authenticated ACL; direct JSON rewrites differ from the canonical vault. The separate hybrid adapter actually calls the canonical retrieval kernel.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S195]] — same-file-bytes
- [[Evidence/S198]] — same-file-bytes
- [[Evidence/S191]] — same-file-bytes
- [[Evidence/S197]] — same-file-bytes
- [[Evidence/S192]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
