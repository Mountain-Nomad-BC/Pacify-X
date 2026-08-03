# Project Blueprint

## Executive summary

The Engineering Loop Bootstrap is a standard-library Python control plane and packaged skill/orchestration library for governed, evidence-driven engineering work. A user installs or places the bootstrap, chooses the new-project or existing-project prompt, and gives that prompt to an LLM.

## Problem and users

Large skill libraries and source corpora can overload model context and local tooling. Users need an assistant to discover capabilities without loading them all, preserve repository ownership, require approval for effects, persist project state, recover after interruption, and prove outcomes.

## Scope

- New-project commissioning with proposal and explicit apply.
- Existing-project read-only inventory and collision-preserving adoption.
- Durable project management and compact commissioning dossier.
- Metadata-only startup, bounded selection, explicit hydration, and unload-on-command-exit.
- Typed policies, registries, graphs, models, builders, orchestrations, evidence, recovery, and quarantine.
- Model-neutral instruction files, TOML profiles, and safe VS Code settings.

## Non-goals

- Selecting a provider, model, credential, or paid service for the user.
- Automatically installing tools, connecting production systems, deploying, or mutating without approval.
- Treating reference research, generated candidates, or executor claims as production proof.

## Core workflows

New: validate bootstrap → preview commission → approval → apply → complete project brief → project-check/startup → bounded working-set/hydrate → approved implementation → independent verification.

Existing: validate bootstrap → read-only intake → preview preserve/create plan → approval → collision-safe apply → reconcile architecture truth → bounded working-set/hydrate → minimal owner-compatible work → independent verification.

## Non-functional requirements

Fail closed; maximum three selected capabilities; one heavy lane by default; no eager skill-body copying; no hard deletion; deterministic hashes and receipts; no provider or machine-specific credentials; Windows-compatible paths; clean installed-wheel operation.

## Success criteria

Both prompt paths complete from a clean installed wheel, existing owner hashes remain unchanged, startup reports zero hydrated bodies, explicit hydration loads one admitted body, project management and dossier files exist, registries and schemas validate, the full test suite passes, package contents reconcile, and the active-tree sanitization audit reports zero findings.
