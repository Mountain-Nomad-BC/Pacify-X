---
name: self-host-supabase
description: Evaluate, deploy, secure, update, and operate self-hosted Supabase with ownership of every service.
---

# self-host-supabase

## Outcome

Evaluate, deploy, secure, update, and operate self-hosted Supabase with ownership of every service.

## Suggest or activate when

- Control, locality, customization, or disconnected operation requires self-hosting.

## Do not suggest or activate when

- Do not describe self-hosting as operationally equivalent to managed Supabase.
- Do not expose default credentials, Studio, or admin APIs.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Inventory services, versions, orchestrator, Postgres/storage durability, SMTP, TLS, identity, secrets, backups, logs, scaling, and update ownership.
2. Use the official reference as a baseline; replace every default, pin images, minimize ingress, harden networks, configure auth URLs/email, and add health/backup/restore controls.
3. Stage upgrades, track divergence from upstream, and test loss/recovery of hosts and stateful services.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- No default secret remains.
- Restart/host loss preserves data.
- All required services pass functional tests.
- Restore and upgrade paths are demonstrated.

Capture the selected environment, versions, authority, redacted configuration or command evidence, test identifiers, observed external outcome, rollback point, and unresolved risks. A successful command proves only that command; verify the requested real-world result separately.

## Common failure modes

- Service-role access hides broken RLS.
- CLI linkage or project reference points to the wrong environment.
- Dashboard state is not represented in migrations.
- Client code exposes privileged credentials or ignores returned errors.

## PACIFY-X governance hooks

Load metadata at startup and this body only after semantic selection. Before installation, credentials, external calls, deployments, production actions, or schema changes, route through the existing controls that apply:

- `discover-environment-safely`
- `quarantine-external-tools`
- `supervise-contained-execution`
- `validate-contract-boundaries`
- `certify-reversible-validation`
- `verify-outcome`

## References

- https://supabase.com/docs/guides/self-hosting
