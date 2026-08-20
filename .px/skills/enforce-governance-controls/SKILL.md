---
name: enforce-governance-controls
description: Apply fail-closed authorization, source visibility, service-only mutation, lifecycle proof, workflow integrity, staged admission, containment, trace sanitization, evidence immutability, cleanup selection, and freshness controls. Use for privileged workflows, retrieval, imports, cleanup, or completion certification.
---

# Enforce Governance Controls

1. Resolve identity and policy from trusted server-side context; client roles are descriptive only.
2. Declare inputs, effects, source visibility, approval, postconditions, and evidence before execution.
3. Read only the relevant control reference.
4. Deny unknown states/effects and keep candidates inert until validation passes.
5. Verify postconditions and current evidence independently of executor claims.

- Authorization, visibility, mutation: [authorization-visibility.md](references/authorization-visibility.md)
- Sessions, workflows, evidence, freshness: [lifecycle-evidence.md](references/lifecycle-evidence.md)
- Admission, containment, traces, cleanup: [containment-cleanup.md](references/containment-cleanup.md)
