---
name: use-n8n-mcp
description: Expose or consume n8n capabilities through MCP with narrow tools, authentication, schemas, approvals, and injection defenses.
---

# use-n8n-mcp

## Outcome

Expose or consume n8n capabilities through MCP with narrow tools, authentication, schemas, approvals, and injection defenses.

## Suggest or activate when

- An AI client should invoke approved n8n workflows.
- n8n must consume an MCP server.

## Do not suggest or activate when

- Do not expose every workflow or credential-backed action.
- Do not connect an untrusted client directly to production automation.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Determine MCP direction, client, transport, auth, tool/workflow allowlist, schemas, data sensitivity, and approval requirements.
2. Expose only eligible capabilities with clear schemas; validate all inputs; use read-only behavior by default; require approval for destructive or external side effects.
3. Separate environments, add audit/rate limits, test malformed and injected content, and keep immediate revocation available.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Only approved tools are discoverable.
- Unauthorized or injected calls fail.
- Tool result reflects verified workflow outcome.

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

- https://docs.n8n.io/advanced-ai/accessing-n8n-mcp-server/
- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcpclient/
