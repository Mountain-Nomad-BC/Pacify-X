---
name: design-n8n-supabase-reliability
description: Design reliable n8n-Supabase behavior for retries, duplicates, partial failure, transactions, concurrency, and backpressure.
---

# design-n8n-supabase-reliability

## Outcome

Design reliable n8n-Supabase behavior for retries, duplicates, partial failure, transactions, concurrency, and backpressure.

## Suggest or activate when

- Cross-system automation has material side effects or production reliability requirements.

## Do not suggest or activate when

- Do not claim distributed atomicity between n8n and external systems.
- Do not retry without operation-specific idempotency.

## Discover before acting

- Confirm both n8n and Supabase versions/environments, the data direction, credential type, authorization context, and transaction boundaries.
- Inspect existing workflows, migrations, RLS, and integration paths before changing either side.

## Procedure

1. Map every state transition, transaction boundary, side effect, dedupe key, timeout, concurrency risk, retry class, and recovery owner.
2. Use Postgres transactions/RPC for atomic Supabase mutations, unique constraints/idempotency records, and outbox/inbox patterns for durable transfer.
3. Add bounded backoff, dead-letter/manual review, optimistic locking where needed, reconciliation, backpressure, and worker/network failure tests.

## Best practices

- Keep n8n orchestration, Supabase durability/RLS, and external side effects as explicit separate trust and transaction boundaries.
- Use idempotency, unique constraints, outbox/reconciliation patterns, least-privilege credentials, and end-to-end outcome checks.
- Test with user-scoped roles before privileged bypass credentials.

## Verification and evidence

- Duplicate delivery is harmless.
- Partial failure resumes or compensates.
- Concurrent runs preserve invariants.
- Reconciliation repairs drift.

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

- https://docs.n8n.io/flow-logic/error-handling/
- https://supabase.com/docs/guides/database
