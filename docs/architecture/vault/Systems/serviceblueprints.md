---
canonical_id: "serviceblueprints"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# SQL and queue deployment blueprints

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Defines an owner-scoped SQL table with RLS policies, a separate vector schema and query function, and an n8n main/worker queue composition.

## Historical source state

Schema and deployment declarations; vector dimension 1536; bounded match count; image placeholder.

## Limits and unknowns

The vector template enables RLS but defines no policies or explicit tenant predicate. Effective access depends on separately configured roles and policies. The n8n composition has an image placeholder and no dependency health conditions; it is a scaffold.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4060]] — same-file-bytes
- [[Evidence/S4057]] — same-file-bytes
- [[Evidence/S4058]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
