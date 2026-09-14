---
canonical_id: "oslock"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Process-bound filesystem lock

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Acquires an OS byte lock with bounded jittered retry, maintains a token and process-start-bound lease, and retains recovery evidence for stale metadata.

## Historical source state

OS lock, heartbeat metadata, process identity and recovery receipt.

## Limits and unknowns

The OS lock is authoritative. A live PID with unavailable start identity is conservatively treated as live; expiry alone is not permission to steal it.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2178]] — same-file-bytes
- [[Evidence/S2176]] — same-file-bytes
- [[Evidence/S2180]] — same-file-bytes
- [[Evidence/S2177]] — same-file-bytes
- [[Evidence/S3193]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
