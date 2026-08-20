---
name: configure-n8n
description: Configure n8n URLs, database, encryption, execution, logging, retention, and runtime settings from an explicit contract.
---

# configure-n8n

## Outcome

Configure n8n URLs, database, encryption, execution, logging, retention, and runtime settings from an explicit contract.

## Suggest or activate when

- An installed instance needs environment-specific configuration.

## Do not suggest or activate when

- Do not paste a giant environment file without selecting applicable settings.
- Do not place secrets in source control, command arguments, or diagnostic output.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Determine topology, database, ingress/TLS, editor and webhook URLs, proxy headers, execution mode, binary-data mode, logs, email, and retention.
2. Create a minimal version-specific configuration contract and inject secrets through protected runtime mechanisms.
3. Restart behind the actual proxy and verify callback URLs, credential decryption, retention, and redaction.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Editor and webhook URLs resolve correctly.
- Credentials decrypt after restart.
- Configuration drift and secret leakage checks pass.

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

- https://docs.n8n.io/hosting/configuration/environment-variables/
