---
name: implement-supabase-auth
description: Implement Supabase Auth with correct client/server sessions, redirects, JWT/RLS integration, lifecycle, and abuse controls.
---

# implement-supabase-auth

## Outcome

Implement Supabase Auth with correct client/server sessions, redirects, JWT/RLS integration, lifecycle, and abuse controls.

## Suggest or activate when

- A project needs signup, login, OAuth, OTP, magic links, SSR, MFA, recovery, or user management.

## Do not suggest or activate when

- Do not equate authentication with authorization.
- Do not expose admin credentials to clients.
- Do not accept arbitrary redirect URLs.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Choose auth methods, clients/platforms, SSR boundary, domains, redirect URLs, email/SMS provider, user profile mapping, lifecycle, MFA, rate limits, and RLS claims.
2. Configure providers and exact redirects, use the correct client/server session package, validate server-side state, and map identities to application rows safely.
3. Implement verification, refresh, logout/revocation, recovery, deletion, rate/abuse controls, and database authorization tests.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Wrong-user and unauthenticated access fail.
- Redirect attacks are blocked.
- Session refresh/logout/recovery work.
- Admin paths stay server-side.

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

- https://supabase.com/docs/guides/auth
