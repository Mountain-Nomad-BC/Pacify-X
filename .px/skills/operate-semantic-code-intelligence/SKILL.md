---
name: operate-semantic-code-intelligence
description: Operate admitted semantic AST/LSP/project/query/context capabilities with explicit project authorization, revision-bound reads/edits, bounded hydration and source evidence.
---

# Operate Semantic Code Intelligence

Use the existing semantic-code/LSP/integration stack; do not create an alternate code index or language-server authority.

## Sequence

1. Bind the request to an authorized project and exact semantic operation.
2. Resolve current document/project/index revisions before querying or preparing edits.
3. Prefer exact symbol/reference/import/diagnostic operations before broader fused retrieval.
4. Keep cross-project reads explicit and read-only unless a separate owner authorizes mutation.
5. Materialize only bounded context with stable source IDs, revisions and citations.
6. For edits, separate preview from write and reject stale revision/range/position data.
7. Treat LSP results and semantic indexes as derived evidence, not repository authority.
8. Record query/materialization receipts sufficient to reproduce the selected evidence.

## Boundaries

- Never hydrate an entire codebase because a semantic query is ambiguous.
- Never convert an LSP/backend failure into an empty successful result.
- Never infer write authority from a successful read query.

## Completion

Return project scope, operation, semantic/index revisions, selected source IDs, bounded materialized context, exclusions and any separately required mutation authority.
