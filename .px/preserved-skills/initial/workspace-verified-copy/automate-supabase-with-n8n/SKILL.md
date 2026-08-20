---
name: automate-supabase-with-n8n
description: Automate Supabase events and operations through n8n with authenticated triggers, idempotency, durable state, and reconciliation.
---

# automate-supabase-with-n8n

## Outcome

Automate Supabase events and operations through n8n with authenticated triggers, idempotency, durable state, and reconciliation.

## Suggest or activate when

- Supabase changes should trigger notifications, enrichment, synchronization, approvals, or external processes.

## Do not suggest or activate when

- Do not poll blindly when event-driven delivery fits.
- Do not assume a green node chain gives cross-system atomicity.

## Discover before acting

- Confirm both n8n and Supabase versions/environments, the data direction, credential type, authorization context, and transaction boundaries.
- Inspect existing workflows, migrations, RLS, and integration paths before changing either side.

## Procedure

1. Define source event, payload, transaction timing, delivery semantics, dedupe key, side effects, retry classes, latency, and reconciliation.
2. Choose database webhook/Edge Function, scheduled query, or outbox/queue based on durability; authenticate and validate input.
3. Persist event state, make each side effect idempotent, classify retry versus rejection, update outcome, and reconcile missed or partial work.

## Best practices

- Keep n8n orchestration, Supabase durability/RLS, and external side effects as explicit separate trust and transaction boundaries.
- Use idempotency, unique constraints, outbox/reconciliation patterns, least-privilege credentials, and end-to-end outcome checks.
- Test with user-scoped roles before privileged bypass credentials.

## Verification and evidence

- Duplicate events are harmless.
- Lost callbacks are recoverable.
- Partial failure converges.
- Audit maps source event to final outcome.

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
- https://supabase.com/docs/guides/database/webhooks
