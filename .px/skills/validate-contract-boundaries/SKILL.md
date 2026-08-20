---
name: validate-contract-boundaries
description: Compare provider and consumer ownership, routes, methods, versions, schemas, required fields, authorization scopes, and negative-path tests. Use for OpenAPI or JSON Schema changes, frontend/backend payload mismatches, event contracts, database-facing interfaces, API integration failures, or any shared contract migration.
---

# Validate contract boundaries

1. Identify the canonical provider and every known consumer. Do not infer ownership from a generated client or copied schema.
2. Normalize each surface into `runtime.foundation_assurance.ContractSurface` records.
3. Run `compare_contract_surfaces`; treat missing owners, routes, required fields, types, versions, and permission scopes as fail-closed findings.
4. Trace confirmed mismatches through the dependency graph before proposing edits.
5. Add focused positive, denial, malformed-input, compatibility, and rollback tests at the owning boundary.
6. Re-run the comparison and the smallest authoritative contract/integration tests.
7. Report unconsumed providers separately; unused does not prove safe removal.

Also reconcile these boundary classes when present:

- producer routes and schemas against every generated and handwritten consumer;
- intended route/role access against browser-observed navigation, denial behavior, and session state;
- storage identifiers, migration names, table/collection names, and persistence keys across code, configuration, migrations, and deployed state;
- development authentication or bypass paths against production build and runtime configuration.

Static agreement does not certify a live boundary. Record static intent and runtime observation separately, and fail closed on unexplained drift.

For framework adapters, compare behavior against the framework's canonical in-memory implementation: object and ID semantics, lazy construction, sync/async behavior, duplicate policy, filters, score conventions, persistence/configuration round trips, deletion/upsert behavior, thread safety, and documented limitations. Similar method names do not prove contract compatibility.

Read [boundary contract](references/boundary-contract.md) for normalization and evidence rules.

This skill is read-only until a separately authorized implementation step. Generated specifications and external source trees are evidence, not automatic canonical owners.
