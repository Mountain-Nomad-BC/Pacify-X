---
name: build-n8n-supabase-rag
description: Build governed RAG ingestion and retrieval with n8n and Supabase pgvector.
---

# build-n8n-supabase-rag

## Outcome

Build governed RAG ingestion and retrieval with n8n and Supabase pgvector.

## Suggest or activate when

- n8n should ingest documents, create embeddings, retrieve from Supabase, or support an AI workflow.

## Do not suggest or activate when

- Do not deploy without retrieval evaluation.
- Do not apply authorization only after retrieval.
- Do not silently mix embedding models or dimensions.

## Discover before acting

- Confirm both n8n and Supabase versions/environments, the data direction, credential type, authorization context, and transaction boundaries.
- Inspect existing workflows, migrations, RLS, and integration paths before changing either side.

## Procedure

1. Define corpus, chunking, provenance, model/dimension, tenant metadata, update/delete semantics, top-k, query set, recall, latency, and cost.
2. Create the vector schema and matching RPC, enforce tenant/RLS filters inside the query, and implement content-hash/source-ID idempotent ingestion.
3. Batch and checkpoint embeddings, use the consolidated Supabase Vector Store node, evaluate filtered recall/result sufficiency, and version re-embedding.

## Best practices

- Keep n8n orchestration, Supabase durability/RLS, and external side effects as explicit separate trust and transaction boundaries.
- Use idempotency, unique constraints, outbox/reconciliation patterns, least-privilege credentials, and end-to-end outcome checks.
- Test with user-scoped roles before privileged bypass credentials.

## Verification and evidence

- Golden queries meet thresholds.
- Cross-tenant retrieval is impossible.
- Reingestion is idempotent.
- Delete/update and partial-batch recovery work.

Capture the selected environment, versions, authority, redacted configuration or command evidence, test identifiers, observed external outcome, rollback point, and unresolved risks. A successful command proves only that command; verify the requested real-world result separately.

## Common failure modes

- n8n and Supabase each look healthy while the business state is inconsistent.
- Privilege bypass is used instead of correct user authorization.
- A retry duplicates a cross-system side effect.
- Schema, node, credential, or embedding contracts drift independently.

## PACIFY-X governance hooks

Load metadata at startup and this body only after semantic selection. Before installation, credentials, external calls, deployments, production actions, or schema changes, route through the existing controls that apply:

- `discover-environment-safely`
- `quarantine-external-tools`
- `supervise-contained-execution`
- `validate-contract-boundaries`
- `certify-reversible-validation`
- `verify-outcome`

## References

- SOURCE:n8n Supabase Vector Store implementation
- https://supabase.com/docs/guides/ai
