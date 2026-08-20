---
name: commission-project
description: Commission a new repository or safely adopt an existing repository with bounded configuration, durable project-management controls, a read-only inventory, collision-preserving integration, two model-neutral startup prompts, and metadata-first skill routing. Use when establishing this bootstrap in a new project or adding it to an existing codebase without overwriting local owners.
---

# Commission Project

For managed multi-project operation, commission through the workspace surface: initialize the workspace, place existing repositories directly below `projects/` or create a new project with `workspace create-project`, and then run `workspace discover`. Direct `commission` remains the standalone single-project adapter.

1. Resolve and validate the explicit project root.
2. Run proposal mode first: `engineering-bootstrap commission --mode <new|existing> --project <path>`.
3. For an existing project, inspect instruction, configuration, task, build, test, CI, security, and ownership files read-only. Store the inventory with the adoption receipt.
4. Review the per-file `create`, `unchanged`, and `preserve_existing` plan. Preserve differing integration files; treat differences under `.engineering-bootstrap/` as blocking drift.
5. Apply only after approval with `--apply`.
6. Read `PROJECT_MANAGEMENT.md`, the compact three-file commissioning dossier, and `.engineering-bootstrap/AI_ASSISTANT.md`.
7. Run `engineering-bootstrap project-check --project <path>` and `startup --project <path>`; require zero hydrated bodies at startup.
8. Use `working-set` to select at most three metadata candidates and `hydrate --skill <id>` to load one required body.
9. Keep provider, model, credentials, global profile, and permissive approval settings out of project scaffolding.

Read [scaffold-contract.md](references/scaffold-contract.md) before applying or customizing the generated files.
