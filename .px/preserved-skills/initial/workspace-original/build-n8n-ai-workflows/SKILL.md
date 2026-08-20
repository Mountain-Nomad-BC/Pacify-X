---
name: build-n8n-ai-workflows
description: Build n8n AI workflows with bounded model/tool authority, structured outputs, retrieval evidence, evaluation, and escalation.
---

# build-n8n-ai-workflows

## Outcome

Build n8n AI workflows with bounded model/tool authority, structured outputs, retrieval evidence, evaluation, and escalation.

## Suggest or activate when

- A workflow uses LLMs, agents, tools, embeddings, memory, or vector stores.

## Do not suggest or activate when

- Do not grant agents broad production credentials.
- Do not trust model output as validated data or authorize irreversible actions without gates.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Define model role, prompt, input data, tools, retrieval, memory, schema, confidence, cost, latency, injection exposure, and escalation.
2. Limit tools and credentials; validate structured outputs; separate retrieval from authorization; place deterministic checks before side effects.
3. Version prompts/models, add injection and malformed-output evals, bound loops/tokens/timeouts, redact traces, and require human approval for high-impact actions.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Malformed outputs are rejected.
- Injection cannot expand authority.
- Evaluation, cost, and latency gates pass.
- Escalation works.

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

- https://docs.n8n.io/advanced-ai/
