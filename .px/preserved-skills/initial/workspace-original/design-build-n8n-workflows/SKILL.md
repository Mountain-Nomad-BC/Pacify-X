---
name: design-build-n8n-workflows
description: Design maintainable n8n workflows with explicit contracts, modularity, idempotency, errors, and operator evidence.
---

# design-build-n8n-workflows

## Outcome

Design maintainable n8n workflows with explicit contracts, modularity, idempotency, errors, and operator evidence.

## Suggest or activate when

- A new workflow is being built or an existing one is becoming brittle.

## Do not suggest or activate when

- Do not wire nodes before defining the trigger, outcome, side effects, retries, and recovery.
- Do not hide business logic in unreadable expression tangles.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Define input/output schema, side effects, data sensitivity, concurrency, idempotency, retries, compensations, owner, and acceptance criteria.
2. Normalize inputs early, use intent-revealing node names, stable sub-workflow contracts, and idempotency before irreversible actions.
3. Add failure branches, alerts, audit context, fixtures, replay tests, and external outcome verification before activation.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Normal, malformed, empty, duplicate, timeout, and downstream-failure paths pass.
- Repeated delivery does not duplicate effects.
- Operators can recover failures.

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

- https://docs.n8n.io/workflows/
