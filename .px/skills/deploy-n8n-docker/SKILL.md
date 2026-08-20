---
name: deploy-n8n-docker
description: Deploy a durable single-main n8n instance with Docker or Compose, TLS boundaries, health checks, and backup hooks.
---

# deploy-n8n-docker

## Outcome

Deploy a durable single-main n8n instance with Docker or Compose, TLS boundaries, health checks, and backup hooks.

## Suggest or activate when

- A self-hosted development, staging, or modest production deployment is needed.

## Do not suggest or activate when

- Do not use single-main when measured load requires queue mode or HA.
- Do not publish the container directly without ingress and access-control design.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Confirm host capacity, pinned images, Postgres, volume ownership, DNS/TLS, outbound network policy, and backup destination.
2. Use durable volumes, secret injection, a private backend network, a TLS reverse proxy, health checks, and non-production commissioning.
3. Recreate the container and restore from backup to prove persistence and recovery.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Container becomes healthy.
- State survives recreation.
- Inbound and outbound access match policy.
- Restore succeeds.

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
- https://docs.n8n.io/deploy/host-n8n/install-options/use-a-cloud-provider/use-docker-compose
