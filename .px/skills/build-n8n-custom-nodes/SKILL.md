---
name: build-n8n-custom-nodes
description: Develop custom n8n nodes with typed operations, separate credentials, pagination, errors, tests, and release governance.
---

# build-n8n-custom-nodes

## Outcome

Develop custom n8n nodes with typed operations, separate credentials, pagination, errors, tests, and release governance.

## Suggest or activate when

- A stable repeated integration deserves a reusable node.
- An internal API needs a governed n8n interface.

## Do not suggest or activate when

- Do not build a node for a one-off call.
- Do not embed secrets or environment-specific constants.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Define resources, operations, API versions, credentials, pagination, rate limits, error mapping, UX, compatibility, and ownership.
2. Scaffold with official tooling; use declarative style where it fits and a programmatic execute method for complex behavior.
3. Add typed tests, safe credential checks, package scans, isolated installation, version pinning, compatibility notes, and release evidence.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Node loads on the target n8n version.
- Operations handle empty, paginated, and error responses.
- Package gates pass.

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

- https://docs.n8n.io/integrations/creating-nodes/
