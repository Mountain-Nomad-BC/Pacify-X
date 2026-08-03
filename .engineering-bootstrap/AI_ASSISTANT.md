# Model-neutral assistant entry point

1. Read `PROJECT_MANAGEMENT.md`, this file, and the repository's existing instruction owners.
2. Run `engineering-bootstrap validate`, `project-check --project .`, and `startup --project .`; stop closed on failure.
3. Keep startup metadata-only. Run `working-set --goal "<goal>"`, select at most three candidates, then `hydrate --skill <id>` for one required body.
4. Declare effects, approval boundaries, postconditions, rollback, and evidence before execution.
5. Update project-management state at material checkpoints. Verify observable outcomes independently and release selected task context.
6. Preserve existing owners and quarantine cleanup candidates; never hard-delete.
