---
name: scale-n8n-queue-mode
description: Design and operate n8n queue mode with Postgres, Redis, workers, webhook processors, and task runners.
---

# scale-n8n-queue-mode

## Outcome

Design and operate n8n queue mode with Postgres, Redis, workers, webhook processors, and task runners.

## Suggest or activate when

- Execution throughput, isolation, or horizontal scaling exceeds a single process.
- Variable or long-running jobs need worker separation.

## Do not suggest or activate when

- Do not enable queue mode without ownership of Redis, Postgres, workers, and failure recovery.
- Do not assume queue mode supplies business idempotency.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Measure arrival rate, duration, concurrency, payload size, webhook latency, retries, and downstream limits.
2. Use consistent Postgres, Redis, encryption keys, execution mode, and distributed binary-data storage across components.
3. Load-test worker loss, graceful drain, Redis/database pressure, retry duplication, backpressure, and optional external task runners.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- No execution is lost during worker restart.
- Duplicate side effects are prevented.
- Queue age and capacity are observable.

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

- https://docs.n8n.io/deploy/host-n8n/configure-n8n/scaling/enable-queue-mode
- https://docs.n8n.io/deploy/host-n8n/configure-n8n/set-up-task-runners
