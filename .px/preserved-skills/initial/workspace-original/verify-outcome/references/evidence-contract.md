# Evidence contract

## Record fields

Use a stable evidence ID, task ID, evidence kind, source, timezone-aware creation time, sensitivity, and status. Treat evidence as support only when it is current, within the configured freshness window, not future-dated, and scoped to the same task.

## Relationships

Link each record to a claim as `supports`, `contradicts`, or `context`. Preserve contradictions and unresolved references as warnings. Do not let contextual evidence satisfy a claim.

## Decision rules

- `verified`: all postconditions pass and current valid evidence exists.
- `partial`: postconditions pass but current valid evidence is absent.
- `failed`: at least one postcondition fails or none were declared.
- `blocked`: policy disallows the outcome.

Executor self-attestation never substitutes for evidence.
