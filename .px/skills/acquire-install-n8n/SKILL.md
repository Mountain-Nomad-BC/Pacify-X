---
name: acquire-install-n8n
description: Acquire and install n8n through a supported, pinned, reversible channel.
---

# acquire-install-n8n

## Outcome

Acquire and install n8n through a supported, pinned, reversible channel.

## Suggest or activate when

- The user asks how to get, install, update, or run n8n.
- A controlled local or self-hosted environment is required.

## Do not suggest or activate when

- Do not install from an unverified mirror.
- Do not expose an unconfigured instance publicly.
- Do not silently choose Cloud versus self-hosting.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Identify OS, container runtime, Node version, target environment, persistence, network policy, and authority.
2. Choose Cloud, Docker/Compose, or npm from current official guidance; pin the version or image digest.
3. Commission encryption-key custody, durable state, restart persistence, a test workflow, uninstall, and rollback evidence.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Expected version starts.
- Workflows and credentials survive restart.
- Rollback is tested or explicitly bounded.

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

- https://docs.n8n.io/deploy/host-n8n/install-options/install-with-docker
- https://docs.n8n.io/deploy/host-n8n/install-options/install-with-npm
