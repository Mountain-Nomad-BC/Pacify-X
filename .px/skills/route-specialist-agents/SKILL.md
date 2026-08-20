---
name: route-specialist-agents
description: Select and compile a bounded panel from PACIFY-X's local specialist-agent provider. Use when a task materially benefits from a domain specialist or independent reviewer and the agent corpus must remain metadata-first, project-scoped, evidence-governed, and authority-neutral.
---

# Route Specialist Agents

1. Run `engineering-bootstrap agents status` before relying on the provider.
2. Route the explicit task and constraints with `engineering-bootstrap agents route --task "..."`.
3. Reject unresolved or low-confidence routes; do not activate from a lone keyword.
4. Keep exactly one primary and no more than three functionally distinct reviewers.
5. Require an accountable human plus an independent specialist for high-risk work.
6. Create a valid agent task envelope with scope, authority, acceptance criteria, and the active project memory namespace.
7. Compile only the selected panel. Never load the full corpus or a reference-only agent.
8. Treat prompt tools and persona claims as requests, never grants. Runtime authorization remains separate.
9. Require evidence against every acceptance criterion and report blocked or partial outcomes honestly.

Read [runtime contract](references/runtime-contract.md) when compiling a panel, handling high-risk work, or reconciling provider projections.
