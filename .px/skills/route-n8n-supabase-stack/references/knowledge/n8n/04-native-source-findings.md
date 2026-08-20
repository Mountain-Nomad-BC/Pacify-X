
# n8n native source findings

This pack does not redistribute n8n source. It records capability findings from the supplied archive.

## Repository rules found

- pnpm is the repository package manager.
- Fresh setup uses `pnpm agent:setup`.
- Read root and nearest package-local `AGENTS.md`.
- Prefer package-local lint, typecheck, and focused tests while iterating; run required repository-wide gates before completion.
- Never put secrets in command-line arguments.
- Follow existing shared types, error classes, TypeORM persistence, workflow traversal utilities, and lazy-loading patterns.

## Supabase surfaces found in n8n

The archive contains:
- a Supabase API credential;
- a built-in Supabase row CRUD node and tests;
- a consolidated Supabase vector-store node;
- legacy hidden/deprecated vector insert/load nodes;
- an agent-facing Supabase vector-store adapter.

The n8n Supabase credential expects the project base host rather than a manually appended `/rest/v1`. It authenticates using a privileged secret/API key. The built-in node supports row create/get/update/delete and custom schema headers when that schema is exposed by the Data API.

The vector integration expects an existing table and matching RPC, commonly `match_documents`. Selective metadata filtering with approximate indexes can return fewer results than requested. Measure recall and result sufficiency rather than worshiping `top_k` like it pays rent.
