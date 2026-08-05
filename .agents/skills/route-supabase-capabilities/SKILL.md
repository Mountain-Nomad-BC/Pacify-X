---
name: route-supabase-capabilities
description: Route Supabase requests across Postgres, RLS, Auth, Storage, Realtime, Edge Functions, vectors, CLI, self-hosting, and MCP.
---

# route-supabase-capabilities

## Outcome

Route Supabase requests across Postgres, RLS, Auth, Storage, Realtime, Edge Functions, vectors, CLI, self-hosting, and MCP.

## Suggest or activate when

- The request mentions Supabase, RLS, Auth, Storage, Realtime, Edge Functions, pgvector, Supabase CLI, or MCP.

## Do not suggest or activate when

- Do not activate production mutation or elevated-key skills before project scope and authority are explicit.
- Do not assume Cloud when the target is local or self-hosted.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Classify capability, lifecycle stage, environment, and whether access is user-scoped, server-scoped, or administrative.
2. Route database design before client implementation and include RLS whenever client-facing data is involved.
3. Select one primary skill and only necessary supports; record scope and risk.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Correct platform capability and environment are selected.
- Elevated keys and production changes require explicit boundaries.
- RLS dependencies are not omitted.

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

- https://supabase.com/docs
