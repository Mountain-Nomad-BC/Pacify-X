# Model-neutral assistant entry point

This repository is model-agnostic. Any coding assistant must follow `AGENTS.md`, then load only the minimum metadata needed from `bootstrap/startup.toml`, `registry/skill_catalog.toml`, and `policies/policy_index.json`.

## Startup

1. Resolve one explicit project root and one project namespace.
2. Read compact registry and policy summaries only.
3. Select at most three relevant capabilities.
4. Load a selected skill body only after admission and scope checks.
5. Declare effects, budgets, evidence, approval, rollback, and stop conditions before execution.
6. Checkpoint and unload selected task context after the bounded step.

## Non-negotiable boundaries

- Default-deny untagged or foreign-project context.
- Never place private memory, embeddings, prompts, logs, or source into shared indexes.
- Never hard-delete owned or unknown material. Plan, dry-run, hash, quarantine, verify, and await review.
- Never treat an index, model, or external memory provider as the canonical source of truth.
- Never report success from command exit alone; verify revision-bound downstream outcomes.
- Proceed with reversible effects inside the user-approved task scope. Ask for approval only before a destructive effect that cannot be reversed.

## Validation

After the implementation is operationally ready, use the governed section gates, then exactly one owned full test profile and `python -m runtime.cli validate` for certification. Do not use the raw unittest entrypoint as a certification owner. Use `engineering-bootstrap project-check --project .` in a commissioned project.
