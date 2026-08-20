---
name: manage-supabase-environments
description: Isolate local, preview, staging, and production Supabase projects, credentials, links, secrets, and promotion paths.
---

# manage-supabase-environments

## Outcome

Isolate local, preview, staging, and production Supabase projects, credentials, links, secrets, and promotion paths.

## Suggest or activate when

- Multiple environments or branches are required.
- CLI changes need safe promotion.

## Do not suggest or activate when

- Do not trust remembered CLI linkage.
- Do not reuse production service-role keys in local, preview, or CI.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Inventory project refs, regions, branches, URLs, keys, callbacks, connection modes, secrets, domains, and CI identities.
2. Create an environment registry, use separate projects/branches, display and verify targets before remote commands, and keep secrets outside source.
3. Promote migrations/functions through non-production gates and record commit-to-project deployment evidence.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Commands hit the intended project ref.
- Cross-environment credentials fail.
- Promotion evidence and callback URLs match the target.

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
