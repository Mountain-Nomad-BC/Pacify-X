---
name: build-supabase-edge-functions
description: Build Supabase Edge Functions with explicit auth, secrets, CORS, bounds, idempotency, tests, and deployment evidence.
---

# build-supabase-edge-functions

## Outcome

Build Supabase Edge Functions with explicit auth, secrets, CORS, bounds, idempotency, tests, and deployment evidence.

## Suggest or activate when

- Bounded server logic, webhook verification, provider calls, or privileged operations are needed.

## Do not suggest or activate when

- Do not use functions for unbounded long-running jobs.
- Do not expose or log service-role secrets.
- Do not skip JWT or signature decisions.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Define request/response schema, auth/signature, secrets, CORS, timeout, external calls, retries, region, idempotency, and failure destination.
2. Scaffold and test locally; validate input/auth, inject managed secrets, bound calls/retries, return stable errors, and use database transactions/RPC for atomic changes.
3. Deploy through non-production, correlate logs, verify source hash, and test retry/timeout behavior.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Malformed and unauthorized requests fail.
- Retries do not duplicate effects.
- Logs are redacted.
- Deployed source matches tested source.

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

- https://supabase.com/docs/guides/functions
