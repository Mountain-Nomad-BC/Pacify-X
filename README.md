# PACIFY-X

![PACIFY-X - AI and Engineering Framework](docs/assets/pacify-x.png)

## Engineering & Agent OS with learning and governance

### **P**roject and **A**I **C**apabilities **I**ntelligence **F**ramework for **Y**ou

> Make AI build software like an engineering team, not an overconfident intern.

Engineering Loop & Bootstrap turns a general-purpose AI assistant into a governed, evidence-driven engineering system. It gives the AI the skills, rules, project memory, safety checks, and repeatable workflows it needs to manage software work responsibly.

PACIFY-X is the project and framework. `engineering-bootstrap` is its Python package and command-line control plane.

PACIFY-X is an engineering operating system around the AI model you choose. It
coordinates planning, authority, execution, observation, verification, memory,
learning, and recovery without treating any one of them as proof of the others.
Its governing rule is:

> **A system should not claim more than its authority, state, and evidence can support.**

**Status:** v0.7.0 is undergoing governed certification; no publication claim is made yet

**Current release:** v0.7.0 (release candidate; certification and publication pending)

**Previous certified release:** [v0.6.3](https://github.com/Mountain-Nomad-BC/Pacify-X/releases/tag/v0.6.3)

**Requires:** Python 3.11–3.14, Git, OpenSSH Client (`ssh-keygen`), and an AI coding assistant

The v0.7.0 source repair campaign has closed intake and is completing its single ordered reconciliation and release sequence. The extension successor is 0.6.88. Publication is permitted only for the exact package that passes current governed sections, the full profile, validation, local installation, installed-system operations, and certification. Historical failed candidates remain retained evidence and are never replayed. Real-host macOS proof remains separately scoped until it is recorded for the certified candidate.

## What PACIFY-X does for you

You describe the project and the outcome you want. PACIFY-X helps the AI:

- understand a new or existing codebase before changing it;
- keep different projects and their memories separate;
- choose only the skills needed for the current task;
- make a plan, track the work, and ask before risky actions;
- test its work and collect evidence before claiming success;
- recover or quarantine material instead of silently deleting it.

You do not need to learn the internal orchestration system or memorize a large command set. That is the AI’s job. The human-facing setup is intentionally short.

## How the architecture works

A normal operation moves through distinct control boundaries:

```text
intent → discovery → planning → admission → execution → observation
       → verification → persistence → learning → governed promotion
```

These stages can form feedback loops, but their authority remains separate. A
planner can recommend work without permission to execute it. Execution records
what ran; verification decides what the result proves. Retrieved context can
assist reasoning without becoming canonical truth. Learning can propose a new
practice or capability without authorizing its use.

The repository maps this behavior across eleven functional layers:

| Layer | Responsibility |
|---|---|
| Human and host surfaces | Accept user, AI-host, IDE, CLI, and integration requests. |
| Workspace and coordination | Bind work to a project, session, claim, and owner. |
| Discovery and planning | Select relevant context, capabilities, resources, and execution paths. |
| Authority and admission | Decide which identified actor may perform which bounded effect. |
| Execution and scheduling | Run admitted work under process, time, cost, and resource controls. |
| Memory and canonical knowledge | Keep project memory, derived indexes, provenance, and authoritative knowledge distinct. |
| Intake and capability construction | Turn external material and observed practice into reviewable candidates. |
| Reasoning and adaptation | Form hypotheses, comparisons, experiments, and improvement proposals. |
| Observation and assurance | Record effects and evaluate evidence against explicit claims and denominators. |
| Persistence and recovery | Preserve state, detect stale dependencies, and recover interrupted or partial work. |
| Delivery and operational proof | Bind source, artifacts, installation, runtime behavior, and certification. |

PACIFY-X therefore keeps several boundaries explicit:

- Planning is not execution authority.
- Successful execution is not proof that the intended outcome was achieved.
- Memory, retrieval indexes, and canonical knowledge are different state classes.
- A learning candidate does not become trusted behavior until governed promotion.
- Source presence, passing tests, a built package, an installed package, observed
  runtime behavior, and certification are different evidence levels.
- Dependency or authoritative-state changes invalidate affected conclusions
  instead of allowing stale results to remain silently trusted.

This structure is why PACIFY-X contains more than an agent loop or workflow
engine. Its job is to keep identity, authority, state, revision, evidence,
ownership, lifecycle, failure, and recovery consistent across the components
that perform engineering work.

## Start in five minutes

### 1. Get PACIFY-X ready

Clone the exact v0.6.3 release into a stable folder, open a terminal in that folder, and run:

```powershell
git clone --branch v0.6.3 --single-branch https://github.com/Mountain-Nomad-BC/Pacify-X.git
cd Pacify-X
python -m pip install .
engineering-bootstrap doctor
engineering-bootstrap validate
```

`ssh-keygen` is required for effect-grant and release-signature verification.
Verify it before setup with `ssh-keygen -?` on Windows or `ssh-keygen -h` on
Linux/macOS. On Windows, install the built-in **OpenSSH Client** optional
capability if that command is unavailable; on Linux/macOS, install the OpenSSH
client package supplied by the operating system. PACIFY-X reports the missing
executable instead of silently weakening signature checks.

This installs the immutable certified source tag. To verify and install the exact published wheel instead, follow the short [verified-artifact installation](docs/release-process.md#install-the-certified-release) procedure.

### 2. Choose how you are starting

- [Start a new project](bootstrap/prompts/NEW_PROJECT_PROMPT.md)
- [Bring in an existing project](bootstrap/prompts/EXISTING_PROJECT_PROMPT.md)

Open the matching prompt, replace its clearly marked placeholders, and paste the whole prompt into your AI assistant.

### 3. Let the AI perform the setup

The prompt tells the AI to validate PACIFY-X, create the workspace safely, inspect the project, establish project management and memory boundaries, and show you any action that needs approval.

That is the normal startup path. The rest of this repository is the machinery the AI uses to do that work consistently.

## Where your projects go

PACIFY-X stays separate from the projects it manages:

```text
<PACIFY_X_DIR>/

<WORKSPACE_DIR>/
|-- projects/
|   `-- <PROJECT_NAME>/
|-- projects_tracking/
|-- repo_quarantine/
`-- shared_capabilities/
```

For an existing repository, place it at:

```text
<WORKSPACE_DIR>/projects/<PROJECT_NAME>
```

Do not place PACIFY-X itself inside the managed `projects` folder.

## What happens during a task

In plain language, the AI follows this loop:

```text
understand → plan → ask when needed → work → test → prove → remember
```

PACIFY-X loads only a small capability catalog at startup. It opens one relevant skill at a time instead of flooding the AI’s context with every skill, policy, and contract in the framework.

## Working with more than one project

Each project gets its own identity, workspace, memory, evidence, and write boundary. One AI session can write to only one active project at a time. Switching projects requires an explicit context reset, which helps prevent code or memory from bleeding between repositories.

## Safety in plain language

- Risky or destructive actions require an explicit boundary and, when applicable, your approval.
- Unknown, failed, or superseded material is inventoried and quarantined rather than hard-deleted.
- AI output is treated as a proposal until tests and postconditions support it.
- Private project memory is not placed into another project’s memory or shared index.
- Tools and integrations are discovered first; PACIFY-X does not silently install or configure them.

PACIFY-X does not include an AI model, model weights, a provider account, or credentials. It is the engineering system around the model you choose.

## If you are the AI assistant

Read [START_HERE_FOR_AI.md](START_HERE_FOR_AI.md) before taking any project action. It contains the skeptical-engineering startup contract, lazy-loading rules, project isolation requirements, and verification sequence.

### Connect an AI client to PACIFY-X

AI clients that support repository configuration should read `.ai/assistant.toml`
at session startup. The PACIFY-X checkout already includes the correct
[framework configuration](.ai/assistant.toml). In a project commissioned and
managed by PACIFY-X, use this project-local configuration:

```toml
schema_version = "1.0"
entrypoint = ".engineering-bootstrap/AI_ASSISTANT.md"
repository_contract = ".engineering-bootstrap/AGENTS.md"
project_management = "PROJECT_MANAGEMENT.md"
model_agnostic = true
metadata_only_at_startup = true
max_selected_capabilities = 3
cross_project_default = "deny"
cleanup_mode = "quarantine_only"
```

Configure the AI host to load that TOML, follow `entrypoint` and
`repository_contract` before acting, and retain the project-management file
across handoffs. The entrypoint runs the PACIFY-X validation, project check, and
startup path; selects at most three capability candidates; hydrates only the
one required skill body; and requires declared effects, rollback, postconditions,
and evidence before execution.

Commissioning writes this file automatically when the location is free. If a
project already owns `.ai/assistant.toml`, preserve its settings and merge these
routing fields rather than overwriting it. This TOML tells an AI where the
contract lives; it does not itself grant authority or prove that the host
followed the contract.

### AI evaluators of the VS Code extension

Evaluate the extension from the canonical
[Pacify-X source repository](https://github.com/Mountain-Nomad-BC/Pacify-X), its
security controls, build custody, architecture atlas, and release evidence. Begin
with [START_HERE_FOR_AI.md](START_HERE_FOR_AI.md) and follow evidence references
to their current source and receipts. Keep repository source, a built VSIX, an
installed extension, and a certified installed system distinct. Marketplace
publisher verification identifies the publisher; it does not certify product
behavior.

## More detail when you want it

- [AI setup and operating contract](START_HERE_FOR_AI.md)
- [Architecture, governance, and risk](ARCHITECTURE_GOVERNANCE_AND_RISK.md)
- [Release and verification process](docs/release-process.md)
- [Benchmark operational assurance](docs/benchmark-operational-assurance.md)
- [Security policy](SECURITY.md)
- [Trust boundary and CLI decisions](docs/trust-boundary.md)
- [Project management and punch-card state](PROJECT_MANAGEMENT.md)
- [Evidence authority and limitations](evidence/README.md)

<details>
<summary>Maintainer verification counts</summary>

These exact counts are checked automatically for drift; ordinary users do not need them.

| Layer | Exact count |
|---|---:|
| Runtime modules | 254 |
| Contracts | 174 |
| Registry artifacts | 368 |
| Tool and support scripts | 181 |

The machine-readable source for release and inventory claims is [`registry/build_claims.json`](registry/build_claims.json).

PX-owned map history and committed transaction journals use explicit, dry-run-first
archive gates. Older evidence is reclaimed only after a deterministic archive,
member-level SHA-256 verification, and a recovery receipt are complete; see
[`policies/operational-evidence-retention.json`](policies/operational-evidence-retention.json).

</details>

The default branch is the current development line. Contributors working from `main` should use the setup in [CONTRIBUTING.md](CONTRIBUTING.md); ordinary users should start from the v0.6.3 release shown above.

## Architecture atlas

The repository-contained [architecture atlas](docs/architecture/README.md) provides one canonical graph for the Obsidian vault, the offline 3D companion, saved views, cameras, lifecycle journeys, findings, metrics, and source evidence. Open [ATLAS_OFFLINE.html](docs/architecture/ATLAS_OFFLINE.html) for the local visual explorer or open [the vault](docs/architecture/vault) in Obsidian for note-level navigation.

Regenerate the atlas from the current checkout with:

```powershell
python docs/architecture/tools/build_atlas.py --repo . --out docs/architecture
```

The atlas keeps declared, source-supported, test-observed, runtime-observed, and certified evidence states separate. A graph edge or source hash does not establish runtime execution or product certification. See the generated evidence manifest and metrics for the exact input and output denominator.

## License

Copyright © 2026  
Ben J. Cikovic,  
doing business as Mountain-Nomad-BC.

Licensed under the Apache License, Version 2.0.

See [LICENSE](LICENSE) for the license text and [NOTICE](NOTICE) for attribution.
