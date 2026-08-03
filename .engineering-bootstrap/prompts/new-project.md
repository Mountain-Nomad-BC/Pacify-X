# New project bootstrap prompt

You are commissioning a new project with the Engineering Loop Bootstrap located at `<BOOTSTRAP_DIR>`. The new project root is `<PROJECT_DIR>`.

Do not load the skill library into context. Do not install tools, select a model/provider, access credentials, start services, or mutate the target until the user approves the commissioning proposal.

1. Resolve both paths and confirm the target is absent or an intended directory.
2. Validate the bootstrap with `engineering-bootstrap doctor` and `engineering-bootstrap validate`. If the command is not installed, run `python -m runtime.cli --root "<BOOTSTRAP_DIR>" doctor` and the corresponding `validate` command from the bootstrap source checkout.
3. Preview with `engineering-bootstrap commission --mode new --project "<PROJECT_DIR>"`. Show the proposed effects, created files, conflicts, and next approval boundary.
4. Stop for explicit approval before adding the scaffold. After approval, rerun with `--apply`.
5. Read `<PROJECT_DIR>/PROJECT_MANAGEMENT.md`, `<PROJECT_DIR>/.engineering-bootstrap/AI_ASSISTANT.md`, and the generated project-management state. Ask only questions that materially affect objective, users, constraints, risk, architecture, deployment, or acceptance.
6. Run `engineering-bootstrap project-check --project "<PROJECT_DIR>"` and `engineering-bootstrap startup --project "<PROJECT_DIR>"`. Startup must report zero hydrated skill bodies.
7. For each approved goal, run `engineering-bootstrap working-set --goal "<goal>"`, select no more than three metadata candidates, and load one required body with `engineering-bootstrap hydrate --skill <id>`. Release task-specific content after its checkpoint.
8. Update the project-management artifacts from evidence. Execute only approved work packages, verify observable outcomes independently, and preserve cleanup candidates in recoverable quarantine.

If any command, registry, project-root, approval, or evidence check fails, stop closed and report the exact blocker.
