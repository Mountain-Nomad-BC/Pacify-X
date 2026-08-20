---
name: observe-operate-n8n
description: Operate n8n using platform, queue, database, workflow, credential, capacity, and business-outcome observability.
---

# observe-operate-n8n

## Outcome

Operate n8n using platform, queue, database, workflow, credential, capacity, and business-outcome observability.

## Suggest or activate when

- A shared or production instance needs monitoring, alerting, and runbooks.

## Do not suggest or activate when

- Do not monitor only process uptime.
- Do not log full payloads indiscriminately.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Define SLOs for trigger acceptance, success, latency, queue delay, recovery, and business outcomes.
2. Monitor main/worker health, queue depth and age, executions, errors, duration, Postgres/Redis saturation, webhook failures, storage, and credential expiry.
3. Add synthetic end-to-end workflows, bounded-cardinality labels, redaction, actionable alerts, owners, and runbooks.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Synthetic checks prove an external outcome.
- Alerts route to an owner and runbook.
- Capacity headroom and retention are known.

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

- https://docs.n8n.io/hosting/logging-monitoring/
