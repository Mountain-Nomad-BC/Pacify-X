---
name: secure-supabase-rls
description: Design and test Supabase Row Level Security for anonymous, authenticated, service, tenant, and administrative access.
---

# secure-supabase-rls

## Outcome

Design and test Supabase Row Level Security for anonymous, authenticated, service, tenant, and administrative access.

## Suggest or activate when

- Tables are exposed through Supabase clients/APIs.
- Authorization or tenant isolation is required.

## Do not suggest or activate when

- Do not ship client-facing tables without intentional RLS.
- Do not use service-role access to hide missing policy design.
- Do not assume one policy covers every command.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Enumerate roles, identities, tenant relations, operations, sensitive columns, ownership, grants, views, functions, and trusted server paths.
2. Enable RLS, deny by default, write minimal command-specific policies, index policy predicates, and harden security-definer functions/search_path.
3. Test anon, multiple users/tenants, revoked users, insert/update checks, and bypass credentials at the database/API boundary.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Cross-tenant operations fail.
- Expected user operations pass.
- Every command has role-matrix tests.
- Policy query plans remain acceptable.

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

- https://supabase.com/docs/guides/database/postgres/row-level-security
