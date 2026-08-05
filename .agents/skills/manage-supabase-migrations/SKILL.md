---
name: manage-supabase-migrations
description: Create, review, test, deploy, reconcile, and roll back Supabase migrations without dashboard drift.
---

# manage-supabase-migrations

## Outcome

Create, review, test, deploy, reconcile, and roll back Supabase migrations without dashboard drift.

## Suggest or activate when

- Schema, policy, function, trigger, extension, or backfill changes are required.

## Do not suggest or activate when

- Do not manually change production without recording the migration.
- Do not run destructive reset commands against remote production.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Inspect local and remote migration history, schema diff, dependencies, locks, data volume, compatibility, and rollback feasibility.
2. Create a focused migration, review generated SQL for noise, test from clean reset and against existing data, and use expand-migrate-contract for breaking changes.
3. Stage deployment, back up, monitor locks/errors, record irreversible operations, and reconcile drift explicitly.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Fresh and existing databases reach the same expected state.
- Application compatibility holds through transition.
- Migration history matches deployed schema.

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

- https://supabase.com/docs/guides/local-development/managing-environments
