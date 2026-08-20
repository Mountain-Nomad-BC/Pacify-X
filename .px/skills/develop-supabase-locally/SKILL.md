---
name: develop-supabase-locally
description: Run Supabase locally with reproducible config, migrations, seeds, tests, and clean reset behavior.
---

# develop-supabase-locally

## Outcome

Run Supabase locally with reproducible config, migrations, seeds, tests, and clean reset behavior.

## Suggest or activate when

- Local development, CI integration tests, or pre-deployment schema testing is needed.

## Do not suggest or activate when

- Do not use dashboard-only state as the source of truth.
- Do not seed production data or secrets locally.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Check CLI/container versions, config.toml, migrations, seed files, functions, tests, ports, and whether the project is linked remotely.
2. Initialize/start the stack, apply migrations and deterministic synthetic seeds, develop functions locally, and test database/RLS/API behavior.
3. Run a clean database reset from a fresh state to prove reproducibility and ensure no remote project was touched.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Fresh clone starts and resets.
- Schema and seed are deterministic.
- Anon/authenticated/service-role tests pass.
- Remote state is unchanged.

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

- https://supabase.com/docs/guides/local-development
