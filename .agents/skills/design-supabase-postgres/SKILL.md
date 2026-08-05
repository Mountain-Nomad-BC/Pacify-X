---
name: design-supabase-postgres
description: Design Supabase Postgres schemas, constraints, indexes, functions, extensions, and connection patterns.
---

# design-supabase-postgres

## Outcome

Design Supabase Postgres schemas, constraints, indexes, functions, extensions, and connection patterns.

## Suggest or activate when

- A data model, query design, database invariant, or performance plan is needed.

## Do not suggest or activate when

- Do not use the Table Editor as the sole schema record.
- Do not place durable invariants only in application code.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Collect entities, relationships, invariants, transactions, query patterns, tenancy, retention, auth relationships, realtime/vector needs, and connection modes.
2. Model normalized tables, explicit constraints, stable keys, timestamps, and measured indexes; use Postgres functions/transactions for atomic operations.
3. Choose direct/session/transaction pooler connections intentionally and express every change as a reviewed migration.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Constraints reject invalid state.
- Representative queries meet targets.
- A clean migration rebuild matches the design.
- API exposure and RLS are aligned.

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

- https://supabase.com/docs/guides/database/overview
