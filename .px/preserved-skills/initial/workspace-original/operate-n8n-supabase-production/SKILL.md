---
name: operate-n8n-supabase-production
description: Operate a production n8n-Supabase stack with combined SLOs, capacity, cost, backup, security, incident, and change controls.
---

# operate-n8n-supabase-production

## Outcome

Operate a production n8n-Supabase stack with combined SLOs, capacity, cost, backup, security, incident, and change controls.

## Suggest or activate when

- The combined stack is entering or already in production.

## Do not suggest or activate when

- Do not operate it as two unrelated dashboards.
- Do not monitor uptime alone or retain execution/data indefinitely.

## Discover before acting

- Confirm both n8n and Supabase versions/environments, the data direction, credential type, authorization context, and transaction boundaries.
- Inspect existing workflows, migrations, RLS, and integration paths before changing either side.

## Procedure

1. Define business outcomes, dependencies, owners, SLOs, data class, quotas, backup/restore, credential expiry, deployment cadence, and incident channels.
2. Monitor n8n health/queues/executions with Supabase database/API/Auth/Storage/Realtime/Functions, connections, storage, egress, and costs.
3. Add synthetic end-to-end checks, correlated IDs, runbooks, restore/key-rotation drills, staged updates/migrations, reconciliation, and capacity headroom.

## Best practices

- Keep n8n orchestration, Supabase durability/RLS, and external side effects as explicit separate trust and transaction boundaries.
- Use idempotency, unique constraints, outbox/reconciliation patterns, least-privilege credentials, and end-to-end outcome checks.
- Test with user-scoped roles before privileged bypass credentials.

## Verification and evidence

- Synthetic transaction proves the final outcome.
- Alerts map to owners/runbooks.
- Restore and rotation drills pass.
- SLO, capacity, and cost trends are visible.

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

- https://docs.n8n.io/hosting/logging-monitoring/
- https://supabase.com/docs/guides/platform
