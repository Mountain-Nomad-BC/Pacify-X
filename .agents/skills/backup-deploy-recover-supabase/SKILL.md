---
name: backup-deploy-recover-supabase
description: Deploy and recover Supabase schema, data, functions, config, storage, and secrets with tested backups and rollback evidence.
---

# backup-deploy-recover-supabase

## Outcome

Deploy and recover Supabase schema, data, functions, config, storage, and secrets with tested backups and rollback evidence.

## Suggest or activate when

- A production deployment, backup policy, restore, or disaster-recovery drill is needed.

## Do not suggest or activate when

- Do not assume platform backups cover every artifact or objective.
- Do not deploy without verifying the project ref.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Inventory plan backup/PITR features, database size, migrations, functions, storage objects, auth config, secrets, RPO/RTO, and restore destination.
2. Back up required schema/data, test migrations/functions in non-production, deploy with commit/project evidence, monitor, and restore to an isolated environment.
3. Validate Auth, API, RLS, storage, functions, and dependent workflows after restore; document irreversible operations and storage recovery.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Restored schema/data are consistent.
- Platform services and RLS work after recovery.
- RPO/RTO and rollback limits are measured.

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

- https://supabase.com/docs/guides/platform/backups
