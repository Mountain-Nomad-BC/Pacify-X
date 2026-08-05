---
name: install-capabilities-selectively
description: Plan and apply target-specific capability subsets with deterministic
  ownership and rollback. Candidate external-intake bundle; keep inactive until PACIFY-X
  admission and owner review.
---

# Install Capabilities Selectively

## Purpose

Plan and apply target-specific capability subsets with deterministic ownership and rollback.

## Loading rule

Load this candidate metadata only after semantic selection. Load one capability reference at a time. Raw external source material is quarantined as reference-only and must never execute merely because it is present.

## Candidate capabilities

### `plan-selective-capability-installation`

Resolve profiles, modules, components, dependencies, targets, conflicts, and ownership into a deterministic install plan before applying any filesystem changes.

**Use when:** different projects need different capability subsets; cross-harness installation must remain reproducible; updates must know what the framework owns.

**Mechanisms:** profile/module/component manifests; plan then apply; state ledger; incremental update; conflict strategy; uninstall ownership.

**Hard boundaries:** never overwrite unknown files silently; install state is not proof of runtime health; target-specific projections remain derived.

**Proposed PACIFY-X owner:** `skill-bundle-resolver`

## Admission requirements

- Validate behavioral need against the current PACIFY-X owner and semantic index.
- Prefer merging a mechanism into an existing owner over creating a competing control plane.
- Run negative, conflict, rollback, license, and retrieval tests.
- Keep all learned or external content candidate-only until explicit admission.

## Provenance

Sources: everything-claude-code. Everything Claude Code material is MIT licensed and preserved with attribution. HyperLearning-derived entries are clean-room mechanism abstractions only because no source license was found.
