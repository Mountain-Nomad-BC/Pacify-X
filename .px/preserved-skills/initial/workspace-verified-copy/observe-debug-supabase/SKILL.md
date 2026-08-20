---
name: observe-debug-supabase
description: Diagnose Supabase database, API, RLS, Auth, Storage, Realtime, Function, and client failures from correlated evidence.
---

# observe-debug-supabase

## Outcome

Diagnose Supabase database, API, RLS, Auth, Storage, Realtime, Function, and client failures from correlated evidence.

## Suggest or activate when

- A request fails, times out, returns no rows, violates policy, or has connection/performance problems.

## Do not suggest or activate when

- Do not disable RLS or switch to service role as the first debugging move.
- Do not paste keys, JWTs, or personal data into logs or chat.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Capture environment/project ref, request ID, user role, endpoint, query/RPC, status/error, timing, schema/deploy version, and correlated logs.
2. Reproduce with sanitized data and the same authorization context; separate client, network, API, policy, database, pooler, quota, and downstream failures.
3. Inspect policy predicates and query plans, patch minimally, add a regression test, and verify the user-visible outcome.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Root cause explains the evidence.
- The correct role works without bypass.
- Regression fails before and passes after.
- Performance target is restored.

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

- https://supabase.com/docs/guides/platform/logs
