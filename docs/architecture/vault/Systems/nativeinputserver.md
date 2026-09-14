---
canonical_id: "nativeinputserver"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Windows native input request server

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Checks request secret, sequence, root PID creation time and expiry before sending allowed keys.

## Historical source state

Ready marker and per-request sent/refused result files.

## Limits and unknowns

Replay state is in memory; input precedes result publication; no durable intent or per-request path identity/size bound.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S527]] — same-file-bytes

## Directed relationships

- [[Systems/nativeforeground]] — checks process identity then resolves and sends (`E1474`)
