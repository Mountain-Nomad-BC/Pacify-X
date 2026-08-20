---
name: govern-n8n-community-nodes
description: Assess, admit, isolate, pin, update, and retire n8n community nodes as executable supply-chain components.
---

# govern-n8n-community-nodes

## Outcome

Assess, admit, isolate, pin, update, and retire n8n community nodes as executable supply-chain components.

## Suggest or activate when

- A needed integration requires a community node.
- Installed community packages need review.

## Do not suggest or activate when

- Do not install based on download count or convenience alone.
- Do not grant production credentials before code and behavior review.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Identify package, publisher, source, license, maintenance, permissions, dependencies, network behavior, versions, and alternatives.
2. Prefer built-ins or HTTP Request when maintainable; otherwise quarantine, scan, review, pin, test in isolation, document admitted capabilities, and place on an allowlist.
3. Reassess on every upgrade and maintain a workflow migration/removal path.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Package hash and version are recorded.
- No undeclared behavior is observed.
- Removal/replacement works.
- All queue workers use the admitted version.

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

- https://docs.n8n.io/integrations/community-nodes/installation/
