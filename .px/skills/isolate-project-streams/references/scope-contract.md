# Project scope contract

Every operation carries stable workspace, project, agent, session, workstream, lease, intent, and correlation identifiers. Missing or malformed identities deny the operation.

Allowed context is limited to:

- canonical records owned by the active project;
- immutable universal constitution and policy;
- destination-owned material imported through an approved transfer package.

Project switching requires checkpoint creation, released locks, closed handles, flushed retrieval/prompt/embedding/tool caches, revoked old lease, rebound roots, and a negative access test against the old project.

Transfers require source and destination identity, provenance, license, assumptions, tests, sanitization evidence, approval, and destination ownership. A transfer containing private memory is denied.

The operational workspace root contains `projects/`, `projects_tracking/`, `repo_quarantine/`, and `shared_capabilities/`. Only direct children of `projects/` can be registered. The authoritative registry is `projects_tracking/project-registry.json`; session lease projections are stored under `projects_tracking/sessions/<session-id>.json`, while workflow receipts, project state, and memory are stored below `projects_tracking/projects/<project-id>/`.

One session may hold one writable project lease. Distinct sessions may operate distinct projects concurrently; every mutation and memory lookup must resolve the caller's specific session projection rather than a workspace-global current project.

Every registered repository contains `.engineering-bootstrap/workspace-binding.json`. Its workspace ID, project ID, project path, central registry, tracking root, memory namespace, and memory root must match the central projection. Drift denies activation.
