---
name: use-n8n-expressions-and-data
description: Use n8n items, expressions, mappings, and transformations without cardinality, type, or item-linking mistakes.
---

# use-n8n-expressions-and-data

## Outcome

Use n8n items, expressions, mappings, and transformations without cardinality, type, or item-linking mistakes.

## Suggest or activate when

- A workflow needs expressions, mapping, merging, item transforms, or data-shape debugging.

## Do not suggest or activate when

- Do not assume one item when nodes can emit zero or many.
- Do not turn expressions into an invisible general-purpose program.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Inspect actual execution data, item counts, nullability, binary fields, pairing, and node references.
2. Model each boundary, normalize arrays and optional fields, use visible Edit Fields/Set transforms, and reserve Code nodes for genuinely clearer logic.
3. Test empty, multi-item, split/merge, renamed-node, type, and binary-data cases.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Expected item count and schema match.
- Missing fields follow a defined path.
- Pairing and binary data survive transformations.

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

- https://docs.n8n.io/code/expressions/
- https://docs.n8n.io/data/
