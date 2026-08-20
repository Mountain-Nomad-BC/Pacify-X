# Specialist runtime contract

- Metadata discovery opens `registry/agency_agent_registry.json`; it does not hydrate agent bodies.
- The bounded panel is one primary plus zero to three distinct reviewers.
- `active` and `advisory` records may be selected. `reference_only` records remain discoverable for audit and cannot be hydrated.
- The compiled prompt includes the task envelope, runtime policy, selected skills, authority-supplied tools, evidence requirements, handoffs, stop conditions, and result contract.
- Compilation grants no tools, effects, persistence, or execution authority.
- Memory is explicit and namespaced as `project:<project-id>:agent:<agent-id>`.
- High-risk work requires accountable human review and an independent specialist.
- All selected bodies and manifests are verified against their registry hashes before hydration.
- Projected copies reconcile as `Current`, `Outdated`, `Modified`, `Removed`, or `Foreign`; divergent files are preserved before any authorized replacement.
