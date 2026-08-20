---
name: integrate-n8n-webhooks-and-apis
description: Build secure webhook and API integrations with authentication, validation, pagination, rate limits, timeouts, and idempotency.
---

# integrate-n8n-webhooks-and-apis

## Outcome

Build secure webhook and API integrations with authentication, validation, pagination, rate limits, timeouts, and idempotency.

## Suggest or activate when

- n8n receives webhooks or calls REST/GraphQL APIs.
- No dedicated node covers the integration.

## Do not suggest or activate when

- Do not expose unauthenticated production webhooks without an explicit decision.
- Do not blindly retry non-idempotent requests.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Collect API schema, auth, signature method, pagination, limits, timeout, callback behavior, idempotency, and test endpoint.
2. Authenticate and validate inbound requests before side effects; verify signatures using required raw-body semantics.
3. For outbound calls, select columns/fields, paginate completely, classify errors, honor backoff, set bounded retries, and record redacted evidence.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Malformed and forged requests fail.
- Pagination is complete.
- 429/5xx behavior is bounded.
- Replay cannot duplicate effects.

Capture the selected environment, versions, authority, redacted configuration or command evidence, test identifiers, observed external outcome, rollback point, and unresolved risks. A successful command proves only that command; verify the requested real-world result separately.

## Common failure modes

- A green execution is mistaken for a correct external outcome.
- Retries duplicate non-idempotent side effects.
- Secrets or customer payloads leak through exports, logs, or retained execution data.
- Version or deployment assumptions drift from the installed instance.

## PACIFY-X governance hooks

Load metadata at startup and this body only after semantic selection. Before installation, credentials, external calls, deployments, production actions, or schema changes, route through the existing controls that apply:

- `discover-environment-safely`
- `quarantine-external-tools`
- `supervise-contained-execution`
- `validate-contract-boundaries`
- `certify-reversible-validation`
- `verify-outcome`

## References

- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/
- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/
