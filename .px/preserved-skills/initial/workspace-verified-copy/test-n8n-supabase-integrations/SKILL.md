---
name: test-n8n-supabase-integrations
description: Test n8n-Supabase integrations end to end with local services, seeded role matrices, failures, and external outcome assertions.
---

# test-n8n-supabase-integrations

## Outcome

Test n8n-Supabase integrations end to end with local services, seeded role matrices, failures, and external outcome assertions.

## Suggest or activate when

- A workflow, migration, policy, node, or platform version is ready for release.

## Do not suggest or activate when

- Do not test only with service role.
- Do not stop assertions at HTTP 200 or a green n8n execution.

## Discover before acting

- Confirm both n8n and Supabase versions/environments, the data direction, credential type, authorization context, and transaction boundaries.
- Inspect existing workflows, migrations, RLS, and integration paths before changing either side.

## Procedure

1. Identify workflow export, migration version, roles/tenants, fixtures, side effects, failures, and acceptance criteria.
2. Reset local Supabase, apply migrations/seeds, run the tested workflow in isolated n8n, and exercise anon/authenticated/service paths.
3. Test CRUD/RPC/vector/webhook cases plus duplicates, timeouts, rate limits, and database failures; assert durable database and external outcomes and hash artifacts.

## Best practices

- Keep n8n orchestration, Supabase durability/RLS, and external side effects as explicit separate trust and transaction boundaries.
- Use idempotency, unique constraints, outbox/reconciliation patterns, least-privilege credentials, and end-to-end outcome checks.
- Test with user-scoped roles before privileged bypass credentials.

## Verification and evidence

- Every role/operation matrix case is asserted.
- Replay preserves state.
- Fresh reset reproduces results.
- Workflow and migration hashes match the release.

Capture the selected environment, versions, authority, redacted configuration or command evidence, test identifiers, observed external outcome, rollback point, and unresolved risks. A successful command proves only that command; verify the requested real-world result separately.

## Common failure modes

- n8n and Supabase each look healthy while the business state is inconsistent.
- Privilege bypass is used instead of correct user authorization.
- A retry duplicates a cross-system side effect.
- Schema, node, credential, or embedding contracts drift independently.

## PACIFY-X governance hooks

Load metadata at startup and this body only after semantic selection. Before installation, credentials, external calls, deployments, production actions, or schema changes, route through the existing controls that apply:

- `discover-environment-safely`
- `quarantine-external-tools`
- `supervise-contained-execution`
- `validate-contract-boundaries`
- `certify-reversible-validation`
- `verify-outcome`

## References

- https://docs.n8n.io/workflows/
- https://supabase.com/docs/guides/local-development
