---
name: optimize-agent-harness
description: Audit and reduce the gap between available agent tooling and reliable
  task completion. Candidate external-intake bundle; keep inactive until PACIFY-X
  admission and owner review.
---

# Optimize Agent Harness

## Purpose

Audit and reduce the gap between available agent tooling and reliable task completion.

## Loading rule

Load this candidate metadata only after semantic selection. Load one capability reference at a time. Raw external source material is quarantined as reference-only and must never execute merely because it is present.

## Candidate capabilities

### `audit-agent-harness-performance`

Score tool coverage, observation quality, recovery behavior, context efficiency, quality gates, memory, evaluation, security, and cost as one measurable harness surface.

**Use when:** an agent repeatedly stalls or loops; tooling exists but completion quality is poor; harness changes need measurable proof.

**Mechanisms:** deterministic scorecard; before-after deltas; scope-specific checks; action-space audit; observation contract audit; recovery contract audit.

**Hard boundaries:** do not treat file counts as proof of behavior; do not activate external hooks or scripts during audit; preserve target harness ownership.

**Proposed PACIFY-X owner:** `govern-operating-kernel`

### `manage-harness-context-budget`

Measure startup and runtime context load, identify redundant skills/rules/MCP metadata, and compact at phase boundaries without erasing evidence or task state.

**Use when:** context is bloated; skills compete for startup budget; long tasks lose critical state after compaction.

**Mechanisms:** metadata-only startup; phase-boundary compaction; token cost inventory; redundancy detection; minimal hydration.

**Hard boundaries:** never compact away unresolved decisions or evidence links; never load the full catalog merely to estimate it.

**Proposed PACIFY-X owner:** `context-compactor`

## Admission requirements

- Validate behavioral need against the current PACIFY-X owner and semantic index.
- Prefer merging a mechanism into an existing owner over creating a competing control plane.
- Run negative, conflict, rollback, license, and retrieval tests.
- Keep all learned or external content candidate-only until explicit admission.

## Provenance

Sources: everything-claude-code. Everything Claude Code material is MIT licensed and preserved with attribution. HyperLearning-derived entries are clean-room mechanism abstractions only because no source license was found.
