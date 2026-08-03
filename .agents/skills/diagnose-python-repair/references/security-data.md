# Authorization, schema, transaction, and logging repairs

## Diagnose

- Trace identity from trusted authentication output; do not authorize from client-supplied roles.
- Compare serialized payload, validation model, database schema, and migration state.
- Find transaction boundaries, ambient commits, partial writes, and sensitive log fields.

## Repair

- Ground authorization in verified claims plus server policy.
- Make schema changes versioned and backward-compatible or fail with an explicit migration gate.
- Keep one canonical transaction owner and roll back all partial work on failure.
- Use allowlisted structured logging with recursive secret/token/identifier redaction.

## Prove and roll back

- Test forged roles, expired claims, missing fields, old/new schema pairs, rollback, and redaction.
- Verify database and log postconditions, then preserve a reversible migration or feature flag.

Lineage: generalized security and data-integrity patterns; locally revalidated before use.
