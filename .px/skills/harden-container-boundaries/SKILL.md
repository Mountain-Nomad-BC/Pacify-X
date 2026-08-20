---
name: harden-container-boundaries
description: Design or audit container images and service definitions for non-root execution, explicit Linux capabilities, immutable filesystems, isolated networks, bounded resources, health checks, and minimal build context. Use when editing Dockerfiles, Compose files, Kubernetes workloads, or container security baselines.
---

# Harden Container Boundaries

1. Identify the service function and the minimum runtime permissions it actually needs.
2. Use a named non-root UID/GID and verify ownership of every writable path.
3. Drop all capabilities, then add back only individually justified capabilities.
4. Prevent privilege escalation and prefer a read-only root filesystem with explicit temporary mounts.
5. Keep databases and internal services off host ports unless the environment requires a reviewed exception.
6. Set resource limits, startup/readiness/liveness checks, and bounded shutdown behavior.
7. Use multi-stage builds, pinned dependencies, and granular copies; keep secrets and test tooling out of the final image.
8. Validate effective runtime configuration, not only source text.

Do not apply hardening mechanically when it would make required writes or signals impossible. Record each exception, owner, threat, and compensating control.
