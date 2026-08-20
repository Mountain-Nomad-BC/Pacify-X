---
name: maintain-capability-catalog
description: Keep skills, rules, decisions, and workspace recommendations searchable,
  healthy, and non-duplicative. Candidate external-intake bundle; keep inactive until
  PACIFY-X admission and owner review.
---

# Maintain Capability Catalog

## Purpose

Keep skills, rules, decisions, and workspace recommendations searchable, healthy, and non-duplicative.

## Loading rule

Load this candidate metadata only after semantic selection. Load one capability reference at a time. Raw external source material is quarantined as reference-only and must never execute merely because it is present.

## Candidate capabilities

### `maintain-skill-health`

Inventory skills, validate structure and placement, detect duplication or staleness, measure instruction usefulness, and queue targeted repairs instead of blindly accumulating files.

**Use when:** skill count grows faster than maintainability; candidate skills need admission evidence; runtime cannot tell which guidance is stale.

**Mechanisms:** quick scan vs full stocktake; schema validation; placement policy; staleness and duplication checks; quality rubric; health report.

**Hard boundaries:** similarity never authorizes deletion; health score is advisory until evidence is reviewed; preserve provenance and versions.

**Proposed PACIFY-X owner:** `skill-admission-controller`

### `distill-operational-rules`

Extract repeated cross-cutting constraints from admitted skills and evidence, reconcile contradictions, and propose concise always-on rules with explicit scope and source links.

**Use when:** many skills repeat the same invariant; always-on rules are drifting from capabilities; rule bloat needs consolidation.

**Mechanisms:** cross-skill principle extraction; contradiction grouping; scope assignment; append/revise/create decision; source trace.

**Hard boundaries:** do not convert context-specific advice into global law; do not overwrite rule files without review; retain dissenting or exception evidence.

**Proposed PACIFY-X owner:** `forge-skills-from-knowledge`

### `capture-architecture-decisions`

Detect decision moments and record context, constraints, alternatives, rationale, consequences, evidence, and revocation triggers as structured architecture decisions.

**Use when:** a design choice changes system boundaries; future agents need to know why a path was chosen; repeated debates indicate missing decision memory.

**Mechanisms:** decision-moment detection; ADR schema; alternative capture; consequence tracking; supersession links.

**Hard boundaries:** do not fabricate alternatives after the fact; record uncertainty and dissent; ADRs do not override current evidence automatically.

**Proposed PACIFY-X owner:** `propose-change-intelligence`

### `detect-workspace-capability-needs`

Inspect repository languages, frameworks, connected surfaces, MCPs, plugins, and workflows, then recommend the smallest relevant capability bundle with reasons and missing prerequisites.

**Use when:** onboarding an unfamiliar workspace; deciding which domain packs to load; avoiding a full install by default.

**Mechanisms:** project detection; workspace surface inventory; capability-to-surface mapping; minimal bundle recommendation; install readiness checks.

**Hard boundaries:** recommendation does not authorize installation; avoid inferring tools solely from filenames; report ambiguous detection.

**Proposed PACIFY-X owner:** `audit-source-capabilities`

## Admission requirements

- Validate behavioral need against the current PACIFY-X owner and semantic index.
- Prefer merging a mechanism into an existing owner over creating a competing control plane.
- Run negative, conflict, rollback, license, and retrieval tests.
- Keep all learned or external content candidate-only until explicit admission.

## Provenance

Sources: everything-claude-code. Everything Claude Code material is MIT licensed and preserved with attribution. HyperLearning-derived entries are clean-room mechanism abstractions only because no source license was found.
