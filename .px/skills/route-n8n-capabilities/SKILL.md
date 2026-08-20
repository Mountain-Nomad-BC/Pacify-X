---
name: route-n8n-capabilities
description: Route n8n requests to the smallest relevant PACIFY-X capability set.
---

# route-n8n-capabilities

## Outcome

Route n8n requests to the smallest relevant PACIFY-X capability set.

## Suggest or activate when

- The request names n8n, workflow automation, nodes, executions, webhooks, credentials, queue mode, or n8n MCP.
- The project needs integration orchestration but the implementation path is undecided.

## Do not suggest or activate when

- Do not pick n8n merely because work repeats; compare direct code, native automation, queues, and schedulers.
- Do not activate installation or credential-changing skills before environment and authority are known.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Classify the request as fit evaluation, install, workflow design, operation, extension development, AI, MCP, or incident response.
2. Determine Cloud versus self-hosted, environment, data sensitivity, throughput, and reversibility.
3. Select one primary skill and no more than two supporting skills; record why alternatives were rejected.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Only relevant skills are selected.
- State-changing work has an approval and rollback boundary.
- n8n is rejected when a simpler solution fits better.

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

- https://docs.n8n.io/choose-how-to-use-n8n/
