---
name: route-n8n-supabase-stack
description: Route combined n8n and Supabase work across integration, automation, RAG, security, reliability, testing, and operations.
---

# route-n8n-supabase-stack

## Outcome

Route combined n8n and Supabase work across integration, automation, RAG, security, reliability, testing, and operations.

## Suggest or activate when

- A workflow uses n8n with Supabase database, Auth, Storage, Realtime, Functions, or vectors.

## Do not suggest or activate when

- Do not collapse n8n credentials, Supabase user authorization, and database privileges into one trust boundary.

## Discover before acting

- Confirm both n8n and Supabase versions/environments, the data direction, credential type, authorization context, and transaction boundaries.
- Inspect existing workflows, migrations, RLS, and integration paths before changing either side.

## Procedure

1. Classify data direction, trigger, credential mode, user context, side effects, latency, and production scope.
2. Choose among the built-in Supabase node, HTTP Request/Data API, Postgres, webhook/Edge Function, or vector-store node.
3. Add only the needed security, reliability, testing, and operation skills; record rejected paths.

## Best practices

- Keep n8n orchestration, Supabase durability/RLS, and external side effects as explicit separate trust and transaction boundaries.
- Use idempotency, unique constraints, outbox/reconciliation patterns, least-privilege credentials, and end-to-end outcome checks.
- Test with user-scoped roles before privileged bypass credentials.

## Verification and evidence

- The selected path matches transaction and authorization needs.
- Credential/RLS behavior is explicit.
- Replay and failure handling are included.

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

- https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.supabase/
- https://supabase.com/docs
