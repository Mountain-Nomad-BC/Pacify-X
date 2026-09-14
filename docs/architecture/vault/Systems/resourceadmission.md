---
canonical_id: "resourceadmission"
kind: system
layer: scope
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Workstream resource admission policy

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Checks supplied pressure metrics, lane/agent limits and path overlap, assigns worker identifiers and returns admitted/blocked workstream records.

## Historical source state

In-memory lanes, ownership sets and returned assignments.

## Limits and unknowns

dispatch_workstreams constructs a fresh scheduler for that call and does not spawn workers; this policy object is separate from durable process supervision.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3001]] — same-file-bytes
- [[Evidence/S2633]] — same-file-bytes

## Directed relationships

- [[Systems/supervisor]] — requires a separately owned executor (`E242`)
