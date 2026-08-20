# Runtime surface evidence

Use `runtime.foundation_assurance.plan_runtime_surface_validation` to order checks from configuration and static validation through unit, integration, contract, build, health, logs, routes, interactions, accessibility, and rollback.

Map every surface to a canonical owner. Start with read-only configuration/status checks. Building, starting services, probing authenticated routes, or changing state requires declared effects and approval. Verify visible state and network/result contracts; logs alone are not health evidence. Preserve screenshots, request IDs, status output, and test receipts without secrets.
