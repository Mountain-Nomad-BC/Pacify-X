---
name: orchestrate-engineering-loop
description: Route and execute a bounded engineering task through admitted capabilities, explicit effects, checkpoints, evidence assembly, independent verification, and unload. Use for multi-step repository work that must be planned, governed, resumed safely, or proven complete without loading every skill at startup.
---

# Orchestrate Engineering Loop

Keep startup metadata-only. Do not read skill bodies, policies, maps, or repository-wide context until a concrete task requires them.

1. Run `engineering-bootstrap validate`, `engineering-bootstrap contracts status`, and `engineering-bootstrap lifecycle status --project <root>`. Stop closed on an invalid registry/contract corpus and use the returned next-stage contract instead of guessing the process stage.
2. State the task, project root, inputs, postconditions, effects, and budgets.
3. Run `engineering-bootstrap select --goal "<goal>" --input <available-name>` to obtain at most three admitted metadata candidates.
4. Select one capability. Load only its `SKILL.md` and directly required reference.
5. Require explicit approval and an idempotency key for non-read effects.
6. Checkpoint after each material step. Release task-specific context after the step.
7. Assemble claim-to-evidence links and verify postconditions independently of the executor's completion claim.
8. Report `completed` only when every required postcondition passes with current task-scoped evidence. Otherwise report `blocked`, `failed`, or `incomplete` with the exact missing proof.

For any task with multiple deliverables, create or update an enterprise punch card before implementation. Give every card an owner, scope, dependencies, acceptance criteria, required evidence, stop conditions, rollback, and status. The total card denominator is fixed from the accepted scope and changes only through a recorded scope decision. One open, blocked, uncertain, or unverified required card means the requested outcome is incomplete; fast partial execution never reduces that denominator.

Pause and checkpoint when the next step would exceed authorized effects, cross a project boundary, consume an exhausted budget, invalidate rollback, rely on unresolved ownership, or execute without its required evidence adapter. Resume from the checkpoint rather than rebuilding context from memory.

The canonical stage order and required stage evidence live in `registry/engineering_lifecycle.json`. It is metadata, not a substitute for the selected skill body. `lifecycle plan` reports unfinished stages without loading those bodies.

For a registered project-stream workflow, create a request conforming to `contracts/project_stream/workflow-request.schema.json`, including the active `project_id`, `session_id`, approved effects, and idempotency key. Preview it with `engineering-bootstrap workflow run --workspace <root> --request <file>`, obtain approval, then add `--apply`. The runtime resolves identity and lease from that session, rejects missing effects, materializes only bounded typed payloads, persists checkpoints, and writes one idempotent receipt below the active project's tracking root.

Read [runtime-contract.md](references/runtime-contract.md) when defining execution envelopes, recovery, or completion evidence.
