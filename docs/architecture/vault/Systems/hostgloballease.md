---
canonical_id: "hostgloballease"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Global VS Code host lease

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Serializes host workers with an exclusive temporary lock and stale PID check.

## Historical source state

Token/PID lease with best-effort release.

## Limits and unknowns

Two stale collisions can exhaust attempts yet return an uncreated lease; pure VM probe confirms.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S524]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
