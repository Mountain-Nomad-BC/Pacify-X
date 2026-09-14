---
canonical_id: "supabaseprocedures"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Supabase data and operation procedures

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Guides SQL/RLS, auth, client/API, vector search, migrations and cross-stack operational checks with explicit project and user context.

## Historical source state

Host-authored policies/migrations/RPC and environment-specific test evidence.

## Limits and unknowns

The procedures specify work for the host and external platform. Their presence is not proof of configured databases, credentials, indexes or live tenant isolation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S222]] — same-file-bytes
- [[Evidence/S233]] — same-file-bytes
- [[Evidence/S200]] — same-file-bytes
- [[Evidence/S234]] — same-file-bytes

## Directed relationships

- [[Systems/supabasetemplate]] — provides a starting request-handling example (`E325`)
