---
name: dynamic-service-discovery
description: Design or audit service clients and proxies so cached network identity is never trusted beyond its validity window. Use for DNS, registries, orchestrators, proxies, sidecars, container networks, endpoint caches, failover, or recurring stale-address failures; NGINX variable-based DNS is one implementation, not the scope of the skill.
---

# Dynamic Service Discovery

Treat every cached address as a lease, not identity.

1. Identify the authoritative service name/registry, resolver, TTL, health authority, and failure semantics.
2. Resolve at request time or refresh before expiry; never bind service identity permanently to a startup-time address.
3. Separate discovery from health. A resolvable endpoint may still be unready or unauthorized.
4. Bound caches, negative caches, retries, backoff, failover, and connection-pool lifetime.
5. Invalidate endpoints on authoritative change, repeated transport failure, or lease expiry.
6. Preserve identity/authentication checks after re-resolution so discovery cannot redirect trust silently.
7. Test address rotation, restart, scale-out/in, DNS failure, stale pools, partial registry failure, and recovery.
8. Record the discovery contract in the integration registry.

For NGINX in a dynamic container network, a resolver plus variable-based upstream can force re-resolution. Verify URI handling, resolver scope, TTL, and health behavior rather than copying a configuration blindly. Use `scripts/audit_service_discovery.py` for a conservative static warning pass.

When selecting a backend stack, use the vendor-neutral model in `runtime.backend_capabilities`. Cover data, authentication, storage, functions, hosting, model gateways, observability, and payments; route each neutral domain through an explicit provider adapter; prefer the least-effect candidate inside the allowed authority. Metadata discovery never hydrates provider bodies or grants network or mutation authority.
