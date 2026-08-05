---
name: integrate-supabase-data-api-and-clients
description: Use Supabase clients and Data APIs with correct keys, RLS, projection, pagination, errors, typing, and connection boundaries.
---

# integrate-supabase-data-api-and-clients

## Outcome

Use Supabase clients and Data APIs with correct keys, RLS, projection, pagination, errors, typing, and connection boundaries.

## Suggest or activate when

- An app or service uses supabase-js, another SDK, REST, GraphQL, RPC, or direct Postgres.

## Do not suggest or activate when

- Do not expose service-role or database credentials to browsers/mobile clients.
- Do not fetch unbounded tables or assume RLS replaces query design.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Identify runtime, client/server boundary, key type, user context, query patterns, pagination, generated types, transaction needs, and connection limits.
2. Create user-scoped or server-scoped clients correctly, select only required columns, paginate, handle data/error explicitly, and compile generated types.
3. Use RPC/direct database access for atomic multi-step server operations and test RLS under the actual user context.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- No privileged key exists in client bundles.
- Cross-user access fails.
- Queries paginate and errors are handled.
- Types match the schema.

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

- https://supabase.com/docs/guides/api
- https://supabase.com/docs/guides/database/connecting-to-postgres
