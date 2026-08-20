---
name: handle-debug-n8n-executions
description: Diagnose failed, stuck, slow, or incorrect executions from evidence without unsafe reruns.
---

# handle-debug-n8n-executions

## Outcome

Diagnose failed, stuck, slow, or incorrect executions from evidence without unsafe reruns.

## Suggest or activate when

- An execution failed, hangs, returns wrong data, or needs replay.

## Do not suggest or activate when

- Do not rerun side-effecting work until completed effects and idempotency are known.
- Do not dump full customer payloads or secrets into tickets.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Capture execution ID, workflow version, trigger, first divergent node, error, timing, item counts, environment, and downstream state.
2. Reproduce with sanitized fixtures, trace inputs/outputs around the first causal failure, classify the fault, patch minimally, and replay in a bounded scope.
3. Verify the downstream outcome and add a regression fixture before closure.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Root cause explains observed evidence.
- Replay did not duplicate side effects.
- Regression fails before and passes after the fix.

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

- https://docs.n8n.io/flow-logic/error-handling/
