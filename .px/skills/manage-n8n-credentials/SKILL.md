---
name: manage-n8n-credentials
description: Create, scope, rotate, test, and retire n8n credentials without exposing values or breaking hidden consumers.
---

# manage-n8n-credentials

## Outcome

Create, scope, rotate, test, and retire n8n credentials without exposing values or breaking hidden consumers.

## Suggest or activate when

- A workflow needs API, OAuth, database, certificate, or secret rotation support.

## Do not suggest or activate when

- Do not embed secrets in workflow fields, expressions, logs, exports, or chat.
- Do not use broad administrator credentials where a scoped credential exists.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Identify owner, environment, permissions, consumers, rotation method, expiry, external secret support, and audit needs.
2. Create a least-privilege credential, test with a non-destructive operation, map dependencies, rotate with overlap, revalidate workflows, then revoke the old value.
3. Keep separate credentials per environment and trust boundary; retain redacted evidence only.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Intended workflows can use the credential.
- Rotation preserves service and revokes the old secret.
- Exports contain references, not plaintext.

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

- https://docs.n8n.io/credentials/
