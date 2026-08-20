---
name: design-n8n-supabase-security-boundaries
description: Design trust boundaries between n8n users/workflows, Supabase RLS, service credentials, webhooks, logs, and AI tools.
---

# design-n8n-supabase-security-boundaries

## Outcome

Design trust boundaries between n8n users/workflows, Supabase RLS, service credentials, webhooks, logs, and AI tools.

## Suggest or activate when

- The stack handles user data, service-role keys, public webhooks, admin operations, or AI agents.

## Do not suggest or activate when

- Do not expose service-role/database credentials to clients or broad n8n roles.
- Do not use n8n RBAC as a replacement for database RLS.

## Discover before acting

- Confirm both n8n and Supabase versions/environments, the data direction, credential type, authorization context, and transaction boundaries.
- Inspect existing workflows, migrations, RLS, and integration paths before changing either side.

## Procedure

1. Map actors, environments, n8n roles, workflows, credentials, Supabase roles/policies, network paths, webhooks, execution data, and AI/MCP tools.
2. Keep user-facing access user-scoped and RLS-governed; isolate privileged service workflows and credentials.
3. Authenticate/sign webhooks, restrict authoring/execution, redact retained data, separate AI tools from privileged paths, and test rotation/revocation.

## Best practices

- Keep n8n orchestration, Supabase durability/RLS, and external side effects as explicit separate trust and transaction boundaries.
- Use idempotency, unique constraints, outbox/reconciliation patterns, least-privilege credentials, and end-to-end outcome checks.
- Test with user-scoped roles before privileged bypass credentials.

## Verification and evidence

- Cross-tenant and unauthorized workflow tests fail.
- Users cannot retrieve credential values.
- Webhook replay/injection and AI privilege expansion are contained.

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

- https://docs.n8n.io/hosting/securing/overview/
- https://supabase.com/docs/guides/database/postgres/row-level-security
