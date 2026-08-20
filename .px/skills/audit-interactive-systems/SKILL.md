---
name: audit-interactive-systems
description: Verify complete user action paths and final resolved state rather than
  shallow click success. Candidate external-intake bundle; keep inactive until PACIFY-X
  admission and owner review.
---

# Audit Interactive Systems

## Purpose

Verify complete user action paths and final resolved state rather than shallow click success.

## Loading rule

Load this candidate metadata only after semantic selection. Load one capability reference at a time. Raw external source material is quarantined as reference-only and must never execute merely because it is present.

## Candidate capabilities

### `audit-interactive-action-paths`

Trace each interactive control from visibility and event dispatch through API, persistence, and resolved UI state to catch actions that technically fire but produce the wrong final outcome.

**Use when:** buttons all route to one page; individual functions pass but cancel each other out; a deployed UI needs post-release canary verification.

**Mechanisms:** control inventory; event-to-state trace; downstream persistence proof; resolved UI assertion; visual evidence; canary replay.

**Hard boundaries:** click success is not outcome success; avoid destructive production actions; capture evidence at each boundary.

**Proposed PACIFY-X owner:** `triage-cross-surface-failures`

## Admission requirements

- Validate behavioral need against the current PACIFY-X owner and semantic index.
- Prefer merging a mechanism into an existing owner over creating a competing control plane.
- Run negative, conflict, rollback, license, and retrieval tests.
- Keep all learned or external content candidate-only until explicit admission.

## Provenance

Sources: everything-claude-code. Everything Claude Code material is MIT licensed and preserved with attribution. HyperLearning-derived entries are clean-room mechanism abstractions only because no source license was found.
