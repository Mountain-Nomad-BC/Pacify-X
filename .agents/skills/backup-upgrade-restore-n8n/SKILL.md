---
name: backup-upgrade-restore-n8n
description: Back up, upgrade, roll back, and restore n8n with version-aware compatibility and recovery evidence.
---

# backup-upgrade-restore-n8n

## Outcome

Back up, upgrade, roll back, and restore n8n with version-aware compatibility and recovery evidence.

## Suggest or activate when

- An upgrade, migration, backup plan, or disaster-recovery test is needed.

## Do not suggest or activate when

- Do not upgrade production first.
- Do not assume workflow exports alone form a complete backup.
- Do not lose or rotate the encryption key accidentally.

## Discover before acting

- Confirm n8n version, deployment model, environment, authority, data classification, and existing workflows/nodes before acting.
- Read the current official documentation for version-sensitive commands and configuration.

## Procedure

1. Inventory version, database, encryption key custody, binary-data storage, custom/community nodes, runners, configuration, and retention.
2. Create consistent backups, restore to isolated staging, test the target version and custom nodes, run workflow/credential regressions, then promote with rollback bounds.
3. Practice restore periodically and measure RPO/RTO.

## Best practices

- Treat workflows as executable software with owners, versions, contracts, tests, and rollback.
- Use least-privilege credentials, non-production validation, bounded retries, redacted evidence, and external outcome verification.
- Prefer built-in capabilities before community code; pin every deployable version.

## Verification and evidence

- Restored instance boots independently.
- Credentials decrypt and representative workflows run.
- Rollback and recovery objectives are proven.

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

- https://docs.n8n.io/hosting/installation/updating/
