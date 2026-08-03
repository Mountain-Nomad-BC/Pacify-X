# Start Here for AI

This is the required orientation document for any AI assistant entering the Engineering Loop & Bootstrap Framework.

Your job is not to load the repository into context. Your job is to establish one bounded project scope, discover only the capabilities needed for the current task, operate through governed interfaces, and prove outcomes with current evidence.

## First response to the user

Before changing anything:

1. Identify whether the user wants to create a new project, adopt an existing project, maintain this framework, or only inspect/report.
2. State the bootstrap root, intended workspace root, project name/root, and whether the next operation is read-only or mutating.
3. If any of those boundaries are ambiguous and cannot be discovered safely, stop and ask one focused question.
4. Otherwise, continue with read-only validation and preview commands. Do not ask for information that the repository or CLI can determine.

## Mandatory reading order

Read only these entry files at startup:

1. `AGENTS.md` — repository-wide engineering contract.
2. `AI_ASSISTANT.md` — model-neutral operating boundaries.
3. This file.
4. `bootstrap/startup.toml` — compact startup configuration.
5. `registry/skill_catalog.toml` — capability metadata only.
6. `policies/policy_index.json` — policy IDs and routing metadata only.
7. Exactly one mode prompt when commissioning:
   - `bootstrap/prompts/NEW_PROJECT_PROMPT.md`, or
   - `bootstrap/prompts/EXISTING_PROJECT_PROMPT.md`.

Do not recursively read `.agents/skills/`, full policy bodies, evidence archives, graphs, project memory, or knowledge collections during startup. Use catalog metadata to select a bounded working set, then hydrate only the admitted skill needed for the active step.

## Resolve the operating mode

### New project

Use `bootstrap/prompts/NEW_PROJECT_PROMPT.md` as the authoritative commissioning procedure.

Required facts:

- `<BOOTSTRAP_DIR>`: this framework checkout;
- `<WORKSPACE_DIR>`: a separate governed workspace;
- `<PROJECT_NAME>`: a collision-safe project directory name;
- `<AGENT_ID>`: stable identity for the acting agent/team;
- `<SESSION_ID>`: stable identity for the current project session.

Preview workspace initialization and project creation before requesting approval to apply them. Create the project only under `<WORKSPACE_DIR>/projects/<PROJECT_NAME>`.

### Existing project

Use `bootstrap/prompts/EXISTING_PROJECT_PROMPT.md` as the authoritative adoption procedure.

The existing repository must already be directly under `<WORKSPACE_DIR>/projects/<PROJECT_NAME>`, unless the user explicitly authorizes moving it there. Start read-only, inventory the repository, preserve its owner files and established architecture, then preview discovery and commissioning before applying anything.

### Framework maintenance

The active project is this repository. Read `PROJECT_MANAGEMENT.md` and `.engineering-bootstrap/project-management/state.json` before changing control-plane behavior. Treat the current release certificate as revocable: material runtime, contract, registry, policy, model, integration, workflow, package, or evidence changes require proportional validation and recertification.

### Inspection or explanation only

Remain read-only. Gather current evidence and answer the question. A request to review, diagnose, explain, or report does not authorize repairs or external side effects.

## Bounded startup protocol

Run:

```powershell
engineering-bootstrap doctor
engineering-bootstrap validate
engineering-bootstrap startup --project <PROJECT_DIR>
engineering-bootstrap tooling assess --project <PROJECT_DIR>
```

From an uninstalled source checkout, use:

```powershell
python -m runtime.cli --root <BOOTSTRAP_DIR> doctor
python -m runtime.cli --root <BOOTSTRAP_DIR> validate
python -m runtime.cli --root <BOOTSTRAP_DIR> startup --project <PROJECT_DIR>
```

Startup must remain metadata-only and report zero hydrated skill bodies. Do not install tools, choose a model/provider, access credentials, start services, or mutate a project merely because a compatible capability exists.

The startup response includes a read-only tooling assessment. Treat detected tools and project signals as observations. Treat missing-tool suggestions as proposals only. Obsidian may be proposed for documentation-heavy projects; Graphify is reference-only and has governed built-in alternatives. Any installation or configuration requires a separate bounded plan with declared effects and explicit user approval.

## Assistant and IDE integration

The framework root provides model-neutral instructions plus adapters for common assistants and IDEs: `AGENTS.md`, `AI_ASSISTANT.md`, `.ai/assistant.toml`, `.github/copilot-instructions.md`, `.cursor/rules/`, `.windsurf/rules/`, `.codex/`, and `.vscode/`. Commissioning writes managed copies under the project's `.engineering-bootstrap/` directory and installs owner-visible files only when there is no collision. Existing owner files are preserved and reported in the commissioning receipt.

Do not paste every skill or policy into an IDE instruction field. Point the assistant at this file and the applicable owner adapter, keep `bootstrap/startup.toml` metadata-only, and preserve the maximum three-candidate working set. The active project management state, plan, punch cards, approvals, and evidence remain project-local.

## Persistent skeptical-engineer contract

Apply this contract on every session, task, and handoff:

1. Treat user statements, repository documentation, prior-agent notes, model output, and successful command exits as claims—not proof.
2. Separate verified facts, assumptions, unknowns, contradictions, risks, and decisions in the active project-management state.
3. Inspect the smallest sufficient evidence surface, prefer authoritative owners, and trace behavior through contracts, runtime, orchestration, tests, maps, and receipts.
4. Plan material work as acceptance-linked punch cards and dependency-aware waves. Never mark a card complete until implementation, wiring, tests, maps, documentation, and current evidence agree.
5. Use negative, denial, boundary, recovery, and contradiction tests in addition to happy paths. A test suite proves only what its assertions actually exercise.
6. Reopen work when new evidence contradicts a completion claim. Never preserve a status merely because a previous agent or certificate asserted it.
7. Keep skill discovery lazy: metadata first, no more than three candidates, one hydrated skill body at a time, then release task context after its checkpoint.
8. Stop closed when authority, ownership, scope, approval, evidence, or project identity is ambiguous.

The owner adapter must direct the AI to `START_HERE_FOR_AI.md`; this file then routes to the compact startup configuration, catalogs, policies, project-management state, and exactly one commissioning prompt. This is how the behavior remains persistent without loading the entire framework into every context.

## Capability selection protocol

For each approved goal:

1. Classify the task from compact metadata.
2. Request a working set of no more than three candidate skills.
3. Confirm each candidate is admitted for the current scope and effects.
4. Hydrate one chosen skill body.
5. Read only its directly required references.
6. Execute one bounded step.
7. Verify its postconditions independently.
8. Persist a checkpoint/receipt and release task-specific context.

Typical commands:

```powershell
engineering-bootstrap classify --task "<TASK>"
engineering-bootstrap working-set --goal "<GOAL>"
engineering-bootstrap hydrate --skill <SKILL_ID>
engineering-bootstrap plan --goal "<GOAL>"
```

Never hydrate the full skill library. Never treat a declared capability, research note, builder output, or inert candidate as an admitted runtime skill.

## Project isolation

- Resolve one explicit workspace, project ID, project root, agent ID, and session ID.
- One session may hold only one writable project lease.
- Never read or write another project's memory, checkpoints, logs, prompts, or source.
- Use `--context-reset-confirmed` for a same-session project switch or final lease release.
- Reject absolute or parent-traversal request paths that escape the active project.
- Stop on registry drift, binding drift, an expired/foreign lease, or project-root ambiguity.

Use `workspace status` for bounded integrity checks and `workspace monitor` for composed health information. Neither mutates state. Use `workspace rebuild` as a preview and apply it only with explicit approval.

## Effects and approval

Classify an operation before execution:

| Effect | Default behavior |
|---|---|
| Read-only inspection | Proceed within the declared project scope |
| Repository write | Preview, identify targets and rollback, obtain approval when the workflow requires it |
| Install, network, service, migration, or credential access | Require explicit authorization |
| Cross-project operation | Deny unless a specific governed transfer workflow and approval exist |
| Deletion or cleanup | Never hard-delete; inventory, hash, quarantine, verify, and retain a receipt |

A successful process exit is not proof of completion. Require postconditions, current task-scoped evidence, and contradiction checks.

## Workflow execution

Use registered workflows instead of inventing an execution path:

```powershell
engineering-bootstrap workflow list
engineering-bootstrap workflow run --workspace <WORKSPACE_DIR> --request <REQUEST_JSON>
engineering-bootstrap workflow run --workspace <WORKSPACE_DIR> --request <REQUEST_JSON> --apply
```

Preview first. An applied request must have a valid active lease, schema-valid input, complete effect approval, a unique idempotency key, bounded resources, and a timeout that fits within the remaining lease. Keep untrusted or force-cancellable work behind a subprocess/service boundary.

## Memory rules

- Memory is project-scoped, append-only, provenance-bearing, and access-controlled.
- Ingest sources only from inside the active project.
- Candidate and validated records are not retrieval truth.
- Retrieval returns only certified or trusted records.
- A correction is a new evidence-backed candidate; it supersedes an older record only after certification.
- Never allow a caller to provide or select a foreign memory-vault path.
- Process-memory traces may propose inert skills, but they do not become project retrieval memory or self-promote.

## Planning and project management

For material work:

1. Read the active project's `PROJECT_MANAGEMENT.md` and machine-readable state.
2. Translate the request into an explicit plan and independently verifiable punch cards.
3. Record assumptions, unknowns, dependencies, risks, approvals, and acceptance criteria.
4. Keep one active work item at a time unless the orchestration explicitly permits safe parallel work.
5. Close a card only after its implementation, wiring, tests, maps, and evidence agree.
6. Update derived maps after each admitted capability is validated, not before.

Do not use planning directories as permanent homes for operational code. Promote completed behavior into the correct runtime, skill, workflow, contract, policy, registry, test, and evidence locations.

## Completion standard

Do not say "done," "working," "validated," or "deployment-ready" unless the scope-specific gates pass.

For framework control-plane changes, the minimum release checks are:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m runtime.cli --root . validate
python -m runtime.cli --root . contracts status
python -m runtime.cli --root . integrations smoke
python -m runtime.cli --root . graphs status
python -m runtime.cli --root . audit licensing
python -m runtime.cli --root . audit structure
python -m runtime.cli --root . test-profile run fast
python -m runtime.cli --root . test-profile run full
python -m runtime.cli --root . release finalize --release 0.6.2
python -m runtime.cli --root . release verify --release 0.6.2
```

Also verify:

- declared effects match actual effects;
- maps and registries are current;
- tests exercise behavior, denial paths, and recovery paths;
- no active cache, temporary build, embedded archive, or quarantine payload remains in the deployable product;
- sanitization passes;
- the release certificate covers the current material tree or is explicitly marked revoked/pending.

## Stop conditions

Stop closed and report the exact blocker when any of these occurs:

- ambiguous bootstrap, workspace, or project root;
- unexpected mutation during a read-only phase;
- owner-file collision without a preservation plan;
- missing approval for a governed effect;
- registry, hash, binding, graph, or evidence drift;
- expired or foreign project lease;
- cross-project context or memory exposure;
- unbounded retry, resource, timeout, or scheduling behavior;
- missing postcondition evidence or unresolved contradictory evidence.

## Handoff format

When returning control to the user, lead with the verified outcome. Include:

- what changed;
- where it changed;
- tests and validation actually run;
- remaining limitations, blocked gates, or approvals;
- the next safe command or decision, if one remains.

Do not make the user reconstruct the result from progress messages or raw command output.
