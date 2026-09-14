---
canonical_id: "fleetsessionadvance"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Fleet heartbeat transition and restart

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Reconstructs, checks transition and state hash, then publishes canonical event before projection.

## Historical source state

Metadata lifecycle and heartbeat counters.

## Limits and unknowns

Restart does not restart a process; live timestamp check differs from replay.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1528]] — changed-file
- [[Evidence/S1530]] — changed-file

## Directed relationships

- [[Systems/fleetsessionreplay]] — reconstructs before mutation (`E951`)
- [[Systems/eventbuspublication]] — publishes canonical event first (`E952`)
- [[Systems/fleetsessionstate]] — writes next local state (`E956`)
