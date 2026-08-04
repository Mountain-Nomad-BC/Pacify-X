# PACIFY-X

![PACIFY-X - AI and Engineering Framework](docs/assets/pacify-x.png)

## Engineering Loop & Bootstrap Framework

### **P**roject and **A**I **C**apabilities **I**ntelligence **F**ramework for **Y**ou

> Make AI build software like an engineering team, not an overconfident intern.

Engineering Loop & Bootstrap turns a general-purpose AI assistant into a governed, evidence-driven engineering system. It gives the AI the skills, rules, project memory, safety checks, and repeatable workflows it needs to manage software work responsibly.

PACIFY-X is the project and framework. `engineering-bootstrap` is its Python package and command-line control plane.

**Current release:** [v0.6.3](https://github.com/Mountain-Nomad-BC/Pacify-X/releases/tag/v0.6.3)

**Status:** Signed self-certified release published; public assets reproduced and verified

**Requires:** Python 3.11–3.14, Git, and an AI coding assistant

> [!WARNING]
> Version 0.6.2 was revoked and should not be deployed. Use v0.6.3 or later. PACIFY-X self-certification is evidence of its included checks, not an independent security audit or warranty. [See the release evidence and limitations](evidence/README.md).

## What PACIFY-X does for you

You describe the project and the outcome you want. PACIFY-X helps the AI:

- understand a new or existing codebase before changing it;
- keep different projects and their memories separate;
- choose only the skills needed for the current task;
- make a plan, track the work, and ask before risky actions;
- test its work and collect evidence before claiming success;
- recover or quarantine material instead of silently deleting it.

You do not need to learn the internal orchestration system or memorize a large command set. That is the AI’s job. The human-facing setup is intentionally short.

## Start in five minutes

### 1. Get PACIFY-X ready

Clone or copy this repository to a stable folder, open a terminal in that folder, and run:

```powershell
python -m pip install .
engineering-bootstrap doctor
engineering-bootstrap validate
```

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

## More detail when you want it

- [AI setup and operating contract](START_HERE_FOR_AI.md)
- [Architecture, governance, and risk](ARCHITECTURE_GOVERNANCE_AND_RISK.md)
- [Release and verification process](docs/release-process.md)
- [Security policy](SECURITY.md)
- [Project management and punch-card state](PROJECT_MANAGEMENT.md)
- [Evidence authority and limitations](evidence/README.md)

<details>
<summary>Maintainer verification counts</summary>

These exact counts are checked automatically for drift; ordinary users do not need them.

| Layer | Exact count |
|---|---:|
| Runtime modules | 112 |
| Contracts | 82 |
| Registry artifacts | 206 |
| Tool and support scripts | 112 |

</details>

## License

Copyright © 2026  
Ben J. Cikovic,  
doing business as Mountain-Nomad-BC.

Licensed under the Apache License, Version 2.0.

See [LICENSE](LICENSE) for the license text and [NOTICE](NOTICE) for attribution.
