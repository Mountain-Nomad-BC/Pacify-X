---
name: connect-n8n-to-supabase
description: Connect n8n to Supabase through the built-in node, Data API, RPC, or Postgres with correct URLs, schemas, credentials, and RLS semantics.
---

# connect-n8n-to-supabase

## Outcome

Connect n8n to Supabase through the built-in node, Data API, RPC, or Postgres with correct URLs, schemas, credentials, and RLS semantics.

## Suggest or activate when

- n8n must create, read, update, delete, query, or invoke Supabase logic.

## Do not suggest or activate when

- Do not append /rest/v1 to the credential host when the n8n node expects the project base URL.
- Do not expose a service-role key outside controlled server automation.

## Discover before acting

- Confirm both n8n and Supabase versions/environments, the data direction, credential type, authorization context, and transaction boundaries.
- Inspect existing workflows, migrations, RLS, and integration paths before changing either side.

## Procedure

1. Identify operation, schema/table/RPC, volume, user context, transaction need, connection mode, network path, and credential type.
2. Use the built-in node for supported row CRUD, HTTP Request for unsupported Data API/RPC behavior, and Postgres for trusted SQL/transactions.
3. Configure the project base URL, expose custom schemas intentionally, test read-only first, paginate, map errors, and verify RLS or deliberate bypass behavior.

## Best practices

- Keep n8n orchestration, Supabase durability/RLS, and external side effects as explicit separate trust and transaction boundaries.
- Use idempotency, unique constraints, outbox/reconciliation patterns, least-privilege credentials, and end-to-end outcome checks.
- Test with user-scoped roles before privileged bypass credentials.

## Verification and evidence

- Connection and custom schema work.
- Expected user/service role behavior is observed.
- Pagination is complete.
- Workflow exports contain no secret.

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

- SOURCE:n8n Supabase credential and node implementation
- https://supabase.com/docs/guides/api
