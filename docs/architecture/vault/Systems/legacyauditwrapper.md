---
canonical_id: "legacyauditwrapper"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Legacy framework audit reporter

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Invokes composed audit and emits optional JSON/Markdown.

## Historical source state

PASS/FAIL projection and exit.

## Limits and unknowns

External evidence strictness opt-in; writes separate outputs.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S239]] — same-file-bytes

## Directed relationships

- [[Systems/composedaudit]] — invokes canonical framework audit (`E1315`)
