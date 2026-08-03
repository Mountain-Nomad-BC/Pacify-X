# Existing project bootstrap prompt

You are attaching the Engineering Loop Bootstrap at `<BOOTSTRAP_DIR>` to the existing repository at `<PROJECT_DIR>`.

Preserve existing architecture, instructions, source, settings, build/test systems, CI, security controls, and ownership. Begin read-only. Do not load the skill library into context. Do not install tools, access credentials, start services, or write until the user approves the adoption proposal.

1. Resolve both paths and confirm the existing repository root.
2. Validate the bootstrap with `engineering-bootstrap doctor` and `engineering-bootstrap validate`. If the command is not installed, use `python -m runtime.cli --root "<BOOTSTRAP_DIR>" ...` from the bootstrap source checkout.
3. Run `engineering-bootstrap intake --project "<PROJECT_DIR>"` and treat documentation or completion claims as hypotheses until code/runtime evidence supports them.
4. Preview `engineering-bootstrap commission --mode existing --project "<PROJECT_DIR>"`. Review its per-file `create`, `unchanged`, and `preserve_existing` plan. Existing differing files must remain byte-for-byte unchanged.
5. Stop for explicit approval. After approval, rerun the same command with `--apply`; it may add namespaced bootstrap controls and missing integration files but must not overwrite preserved owners.
6. Read `<PROJECT_DIR>/PROJECT_MANAGEMENT.md` when created, plus `<PROJECT_DIR>/.engineering-bootstrap/AI_ASSISTANT.md`, the stored read-only inventory, adoption plan, and project-management state.
7. Run `engineering-bootstrap project-check --project "<PROJECT_DIR>"` and `engineering-bootstrap startup --project "<PROJECT_DIR>"`. Startup must report zero hydrated skill bodies.
8. For each approved goal, use `engineering-bootstrap working-set --goal "<goal>"`, select no more than three metadata candidates, and hydrate one required capability with `engineering-bootstrap hydrate --skill <id>`. Checkpoint and release it after the bounded step.
9. Propose minimal owner-compatible changes, declare effects, require approval where applicable, run the repository's own validation commands, and verify downstream outcomes independently.

Stop closed on project-root ambiguity, unexpected mutation, secret exposure, ownership collision without a preserve decision, registry failure, or missing completion evidence.
