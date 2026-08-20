---
name: evaluate-n8n-fit
description: Evaluate whether n8n fits the workload compared with code, native integrations, or another orchestrator.
---

# evaluate-n8n-fit

## Outcome

Evaluate whether n8n fits the workload compared with code, native integrations, or another orchestrator.

## Suggest or activate when

- A team is considering adoption.
- A script or manual process is becoming brittle or integration-heavy.

## Do not suggest or activate when

- Do not recommend n8n for ultra-low-latency, high-frequency streaming, or simple deterministic work that code handles more clearly.
- Do not confuse visual authoring with reduced operational responsibility.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Capture triggers, volume, latency, retries, approvals, secret scope, data residency, licensing, ownership, and cost.
2. Compare n8n Cloud, self-hosted n8n, direct code, managed queues, and native platform automations.
3. Use a bounded pilot with correctness, recovery, maintainability, and cost gates when evidence is incomplete.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- A decision record lists assumptions and rejected alternatives.
- The pilot has measurable acceptance criteria.
- An exit path is documented.

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
