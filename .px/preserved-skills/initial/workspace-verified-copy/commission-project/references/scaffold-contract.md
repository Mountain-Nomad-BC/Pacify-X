# Scaffold contract

## Files

- `PROJECT_MANAGEMENT.md` plus `.engineering-bootstrap/project-management/`: durable context, assumptions, plan, cards, orchestration, risk, acceptance, and machine-readable checkpoint state.
- `PROJECT_BLUEPRINT.md`, `ARCHITECTURE_GOVERNANCE_AND_RISK.md`, and `EXECUTION_PLAN_PUNCH_CARDS_AND_ACCEPTANCE.md`: compact commissioning dossier.
- `.engineering-bootstrap/AGENTS.md` and `.engineering-bootstrap/AI_ASSISTANT.md`: collision-safe canonical bootstrap instructions.
- `AGENTS.md`: optional root integration; preserve a differing existing owner.
- `.codex/config.toml`: trusted-project settings only. Do not set provider, authentication, global profile, notification, or telemetry keys.
- `.vscode/settings.json`: editor-only `chatgpt.*` behavior and file exclusions.
- `.vscode/tasks.json`: validation, doctor, and test commands.
- `.engineering-bootstrap/project.toml`: bootstrap identity, project mode, and bounded lifecycle settings.
- `.engineering-bootstrap/project-registry.json`: hashes and metadata for canonical installed skills. Skill bodies stay in the framework and are hydrated explicitly rather than copied into the project.
- `.engineering-bootstrap/prompts/`: separate new-project and existing-project copy/paste prompts.

## Collision policy

Create missing files. Record identical files as unchanged. In a new project, any differing target blocks application. In an existing project, preserve differing integration files byte-for-byte and continue with namespaced controls; differing bootstrap-owned files block as drift.

## Existing projects

Inventory first and store the result. Avoid replacing build-system, dependency, editor, instruction, CI, security, or deployment owners. Persist an adoption plan and receipt for every create, unchanged, and preserve decision.
