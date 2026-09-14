---
canonical_id: "nativeforeground"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Owned foreground recovery and SendInput

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Resolves an owned process-tree window, recovers focus and emits exact key down/up pairs.

## Historical source state

Foreground HWND/PID, focus recovery and sent count.

## Limits and unknowns

Process-tree membership does not identify the intended dialog/button; focus and expiry can change between check and input.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S527]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
