---
canonical_id: "handoff"
kind: system
layer: scope
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Agent handoff and context isolation

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Binds a handoff packet to task/project context and checks it before acknowledgment or consumption.

## Historical source state

Packet identities, acknowledgments and consumption records.

## Limits and unknowns

Hash-bound caller metadata, not authenticated sender/receiver signature. Consume validates packet scope/expiry/revision strings and ack packet hash, but does not repeat ack receiver/schema/time checks; hypotheses/open_questions are not returned in consumed view.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1545]] — same-file-bytes
- [[Evidence/S1544]] — same-file-bytes
- [[Evidence/S939]] — same-file-bytes
- [[Evidence/S935]] — same-file-bytes

## Directed relationships

- [[Systems/agent]] — supplies validated scoped context (`E018`)
- [[Systems/agentcallback]] — supplies acknowledged packet identity to governed preview (`E436`)
