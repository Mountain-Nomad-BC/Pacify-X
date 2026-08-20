---
name: inspect-live-contracts
description: Inspect authorized running services to derive effective API, schema, route, and access contracts, then compare them with declared owners and consumers. Use when dynamic registration, runtime configuration, ORM metadata, redirects, or role enforcement makes static contract analysis insufficient.
---

# Inspect Live Contracts

1. Confirm the runtime target, identity, read-only boundary, and authorization.
2. Prefer native OpenAPI/schema/metadata endpoints. Use injected introspection only when no safer interface exists.
3. Execute a minimal read-only payload with a pinned interpreter and no package installation.
4. Surround machine output with unique markers and parse only the bounded content between them.
5. Redact secrets, connection strings, sample values, and session data before persistence.
6. Compare effective routes, methods, fields, identifiers, relationships, and roles with declared owners and known consumers.
7. For access validation, distinguish reachable, redirected, denied, runtime-only, and untested routes.
8. Report drift and uncertainty; do not mutate the running service from the audit path.

Static and live views are separate evidence. A match in one does not certify the other.
