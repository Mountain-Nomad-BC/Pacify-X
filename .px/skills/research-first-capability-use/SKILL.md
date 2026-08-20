---
name: research-first-capability-use
description: Ground current technology use in authoritative, version-aware documentation
  and bounded research. Candidate external-intake bundle; keep inactive until PACIFY-X
  admission and owner review.
---

# Research First Capability Use

## Purpose

Ground current technology use in authoritative, version-aware documentation and bounded research.

## Loading rule

Load this candidate metadata only after semantic selection. Load one capability reference at a time. Raw external source material is quarantined as reference-only and must never execute merely because it is present.

## Candidate capabilities

### `lookup-current-documentation`

Resolve the exact library or product, prefer authoritative current documentation, bound query count, and return source-grounded implementation guidance rather than relying on stale model memory.

**Use when:** APIs or installation steps may have changed; a named framework version matters; implementation depends on current documentation.

**Mechanisms:** library identity resolution; version-aware source selection; official-source preference; query budget; secret redaction; citation trace.

**Hard boundaries:** do not send secrets in research queries; do not exceed query budget without justification; state unresolved uncertainty.

**Proposed PACIFY-X owner:** `research-to-operation-translator`

## Admission requirements

- Validate behavioral need against the current PACIFY-X owner and semantic index.
- Prefer merging a mechanism into an existing owner over creating a competing control plane.
- Run negative, conflict, rollback, license, and retrieval tests.
- Keep all learned or external content candidate-only until explicit admission.

## Provenance

Sources: everything-claude-code. Everything Claude Code material is MIT licensed and preserved with attribution. HyperLearning-derived entries are clean-room mechanism abstractions only because no source license was found.
