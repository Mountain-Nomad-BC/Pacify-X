---
name: acquire-install-supabase
description: Acquire and install the Supabase CLI and official agent resources using supported, pinned channels.
---

# acquire-install-supabase

## Outcome

Acquire and install the Supabase CLI and official agent resources using supported, pinned channels.

## Suggest or activate when

- The user asks how to install Supabase tooling, initialize a project, or add official skills/plugin.

## Do not suggest or activate when

- Do not teach global npm installation of the CLI.
- Do not start local services without a compatible container runtime.
- Do not install AI plugins without reviewing scope.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Identify OS, Node version, package manager, container runtime, project directory, desired CLI scope, and AI-client tooling needs.
2. Prefer a pinned project dev dependency invoked through npm/pnpm/yarn/bun; for global install use supported OS package channels such as Homebrew, Scoop, or Linux packages.
3. Require Node 20+ for npm-run CLI, initialize the project, inspect generated config, start locally, and review any official agent skills/plugin before project-scoped admission.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- CLI help works through the chosen invocation.
- Local stack starts.
- The supabase directory is versioned without secrets.
- No unsupported global npm assumption remains.

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

- https://supabase.com/docs/guides/local-development/cli/getting-started
- https://supabase.com/docs/guides/getting-started/ai-prompts
