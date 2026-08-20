---
name: secure-n8n
description: Harden n8n identity, network, credentials, execution, nodes, updates, and retained data.
---

# secure-n8n

## Outcome

Harden n8n identity, network, credentials, execution, nodes, updates, and retained data.

## Suggest or activate when

- n8n will handle sensitive data, public webhooks, production credentials, code, or AI tools.
- A security review is requested.

## Do not suggest or activate when

- Do not treat login protection as the entire security model.
- Do not enable risky nodes or packages without threat analysis.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Inventory users, roles, credentials, exposed endpoints, enabled nodes, community packages, code execution, runners, outbound paths, logs, retention, and patch level.
2. Reduce public surface, enforce TLS and identity controls, isolate task execution, restrict risky nodes and egress, scope credentials, redact logs, and bound retention.
3. Test webhook forgery/replay, unauthorized workflow access, SSRF-like paths, code execution, credential exposure, and update rollback.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Unauthorized access fails.
- Secrets are absent from exports and logs.
- Accepted risks and security test evidence are recorded.

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

- https://docs.n8n.io/hosting/securing/overview/
