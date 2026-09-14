---
canonical_id: "filelease"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# OS lock and retained process lease

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Acquires advisory lock, checks retained process generation, writes held/released metadata and maintains heartbeat with recovery receipt.

## Historical source state

Live lease, recovery receipt and deferred heartbeat/release errors.

## Limits and unknowns

Heartbeat age is not lease expiry. Release can raise after protected work completed; failed released metadata can leave a live held lease after OS unlock. Thread startup follows acquisition without compensation here.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2175]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
