---
name: evaluate-supabase-fit
description: Evaluate Supabase against direct Postgres, another backend platform, or custom services.
---

# evaluate-supabase-fit

## Outcome

Evaluate Supabase against direct Postgres, another backend platform, or custom services.

## Suggest or activate when

- A project is selecting a database/backend, auth stack, realtime platform, file service, or vector store.

## Do not suggest or activate when

- Do not select it only because prototyping is fast.
- Do not ignore Postgres fit, RLS complexity, compliance, egress, cost, or self-host operations.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Capture data model, transactions, client access, auth, realtime, files, functions, vectors, regions, scale, compliance, portability, and team skills.
2. Compare Supabase Cloud, self-hosted Supabase, managed Postgres plus separate services, and a custom backend.
3. Prototype the highest-risk assumptions: RLS, auth/session flow, connection behavior, backup, performance, and exit path.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Decision record lists assumptions and alternatives.
- Prototype proves the risky boundaries.
- Data portability and reversal are understood.

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
- https://supabase.com/docs/guides/database/overview
