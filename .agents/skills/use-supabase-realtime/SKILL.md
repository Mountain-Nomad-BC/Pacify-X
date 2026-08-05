---
name: use-supabase-realtime
description: Use Supabase Realtime for database changes, broadcast, and presence with authorization and convergence.
---

# use-supabase-realtime

## Outcome

Use Supabase Realtime for database changes, broadcast, and presence with authorization and convergence.

## Suggest or activate when

- A feature needs live updates, collaboration, presence, or event broadcast.

## Do not suggest or activate when

- Do not use Realtime as a durable queue or transactional guarantee.
- Do not subscribe broadly to sensitive tables.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Define event semantics, delivery expectations, authorization, channel cardinality, ordering, reconnect behavior, filters, load, and fallback reads.
2. Choose database changes, broadcast, or presence deliberately; scope channels and policies; filter subscriptions and bound payload/frequency.
3. Implement reconnect/resubscribe and reconcile against durable Postgres state; load-test connections and change volume.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Wrong users cannot subscribe.
- Reconnect converges to correct state.
- Missed or duplicate events cannot corrupt state.
- Load targets pass.

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

- https://supabase.com/docs/guides/realtime
