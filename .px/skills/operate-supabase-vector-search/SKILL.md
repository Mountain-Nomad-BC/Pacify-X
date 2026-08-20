---
name: operate-supabase-vector-search
description: Design and operate pgvector schemas, embedding lifecycle, indexes, filtered matching RPCs, and retrieval evaluation.
---

# operate-supabase-vector-search

## Outcome

Design and operate pgvector schemas, embedding lifecycle, indexes, filtered matching RPCs, and retrieval evaluation.

## Suggest or activate when

- Semantic search, RAG, similarity matching, or n8n's Supabase Vector Store is required.

## Do not suggest or activate when

- Do not select dimensions, metric, or index by cargo cult.
- Do not assume filtered approximate search returns enough rows.
- Do not treat retrieval filters as a substitute for authorization.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Identify embedding model/dimension, metric, corpus size, updates, metadata, filter selectivity, tenancy, top-k, latency, recall, and retention.
2. Create a versioned document/chunk table and stable match RPC, commonly match_documents; enforce RLS/tenant filters inside the query boundary.
3. Start exact, add HNSW/IVFFlat from measurements, index metadata predicates, evaluate recall and minimum result sufficiency, and make re-embedding resumable.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Dimension/model mismatch is detected.
- Authorized golden queries meet recall/latency targets.
- Selective filters return sufficient results or trigger a fallback.
- Re-embedding is restartable.

Capture the selected environment, versions, authority, redacted configuration or command evidence, test identifiers, observed external outcome, rollback point, and unresolved risks. A successful command proves only that command; verify the requested real-world result separately.

## Common failure modes

- Service-role access hides broken RLS.
- CLI linkage or project reference points to the wrong environment.
- Dashboard state is not represented in migrations.
- Client code exposes privileged credentials or ignores returned errors.

## PACIFY-X governance hooks

Load metadata at startup and this body only after semantic selection. Before installation, credentials, external calls, deployments, production actions, or schema changes, route through the existing controls that apply:

- `discover-environment-safely`
- `quarantine-external-tools`
- `supervise-contained-execution`
- `validate-contract-boundaries`
- `certify-reversible-validation`
- `verify-outcome`

## References

- https://supabase.com/docs/guides/ai
- SOURCE:n8n Supabase vector-store implementation
