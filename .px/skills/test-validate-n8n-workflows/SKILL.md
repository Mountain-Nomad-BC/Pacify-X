---
name: test-validate-n8n-workflows
description: Test n8n workflows using fixtures, contracts, failure injection, replay checks, and external outcome assertions.
---

# test-validate-n8n-workflows

## Outcome

Test n8n workflows using fixtures, contracts, failure injection, replay checks, and external outcome assertions.

## Suggest or activate when

- A workflow is ready for activation, modification, or release.

## Do not suggest or activate when

- Do not call one successful manual run complete testing.
- Do not use production credentials or customer data in routine tests.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Identify branches, schemas, side effects, retries, external dependencies, and acceptance criteria.
2. Use sanitized deterministic fixtures and non-production systems; test normal, boundary, malformed, empty, duplicate, timeout, rate-limit, and partial-failure paths.
3. Hash the tested workflow export and assert database/provider state rather than only execution status.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Every intended branch is exercised.
- Workflow and tested export match.
- Replay and recovery are demonstrated.

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
