---
canonical_id: "coordresume"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Coordination handoff publication and reads

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Publishes hashed JSON plus Markdown after a mutation, or derives a task envelope from coordination; MCP also exposes the retained JSON packet directly.

## Historical source state

Stored packet hash/state binding, task scopes/budget/claim/evidence and next-action text.

## Limits and unknowns

The retained-packet MCP handler does not verify packet SHA or current state binding. Task handoff is a different fresh-derived path; workRoom performs two reads without one snapshot lock.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S962]] — changed-file
- [[Evidence/S850]] — same-file-bytes

## Directed relationships

- [[Systems/coordread]] — derives task handoff from current coordination read (`E366`)
