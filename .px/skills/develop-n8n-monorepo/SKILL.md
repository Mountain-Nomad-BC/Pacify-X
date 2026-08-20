---
name: develop-n8n-monorepo
description: Work safely in the supplied n8n monorepo using repository-local agent rules, pnpm, package boundaries, and evidence gates.
---

# develop-n8n-monorepo

## Outcome

Work safely in the supplied n8n monorepo using repository-local agent rules, pnpm, package boundaries, and evidence gates.

## Suggest or activate when

- The task modifies n8n source or contributes upstream.
- Source-level diagnosis needs repository commands.

## Do not suggest or activate when

- Do not use npm or yarn in this repository.
- Do not bypass root or package-local AGENTS.md.
- Do not start with broad expensive gates when focused checks can isolate the change.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Read root and nearest package AGENTS.md, package scripts, setup summary, ownership, generated-file rules, and affected graph.
2. For fresh setup run pnpm agent:setup using the pinned pnpm/Node engines; make the smallest package-scoped change.
3. Run package-local lint, typecheck, and focused tests, then required full repository gates; avoid secrets in CLI args and follow established types, errors, TypeORM, traversal utilities, and lazy loading.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Focused and required broad gates pass.
- Lockfile and unrelated generated files do not drift.
- Diff follows local conventions.

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

- SOURCE:n8n-master/AGENTS.md
