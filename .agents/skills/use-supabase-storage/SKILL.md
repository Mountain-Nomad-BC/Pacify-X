---
name: use-supabase-storage
description: Design Supabase Storage buckets, paths, uploads, signed access, transformations, and RLS policies.
---

# use-supabase-storage

## Outcome

Design Supabase Storage buckets, paths, uploads, signed access, transformations, and RLS policies.

## Suggest or activate when

- A project stores user files, private documents, media, or generated artifacts.

## Do not suggest or activate when

- Do not make a bucket public as a shortcut.
- Do not trust extension, client MIME type, or path as authorization.

## Discover before acting

- Confirm project reference, environment, CLI/platform version, access role, data classification, and whether the target is local, Cloud, or self-hosted.
- Inspect migrations, RLS, environment linkage, and current official documentation before acting.

## Procedure

1. Capture file types, sizes, ownership, tenancy, public/private behavior, upload method, retention, transformation, malware policy, and egress.
2. Define buckets and object naming, write storage-object RLS, use signed URLs for bounded private access, and validate file content before trusted processing.
3. Test resumable/interrupted uploads, overwrite/version semantics, deletion, orphan cleanup, quotas, and unauthorized list/read/write/delete.

## Best practices

- Treat Supabase as Postgres plus integrated services; keep schema and policy changes migration-driven.
- RLS is the client authorization boundary; service-role and database credentials stay in trusted server contexts.
- Use local/non-production validation, synthetic data, explicit project refs, and tested backup/recovery.

## Verification and evidence

- Unauthorized object operations fail.
- Signed URLs expire.
- Interrupted uploads recover.
- Deletion and orphan cleanup are proven.

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

- https://supabase.com/docs/guides/storage
