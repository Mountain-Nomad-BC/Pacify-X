---
name: govern-cross-harness-runtime
description: Project capabilities across harnesses and MCP surfaces without losing
  canonical ownership. Candidate external-intake bundle; keep inactive until PACIFY-X
  admission and owner review.
---

# Govern Cross Harness Runtime

## Purpose

Project capabilities across harnesses and MCP surfaces without losing canonical ownership.

## Loading rule

Load this candidate metadata only after semantic selection. Load one capability reference at a time. Raw external source material is quarantined as reference-only and must never execute merely because it is present.

## Candidate capabilities

### `govern-cross-harness-parity`

Project one canonical capability into Claude, Codex, Cursor, Gemini, Kiro, and OpenCode surfaces while validating semantic parity, target-specific constraints, and reversible installation.

**Use when:** the same skill or agent must work across harnesses; generated projections have drifted; installers target multiple IDEs or CLIs.

**Mechanisms:** canonical source ownership; target adapters; config merge; projection validation; parity tests; target capability flags.

**Hard boundaries:** generated target files are not canonical; unsupported features must be declared rather than simulated; do not overwrite local user configuration silently.

**Proposed PACIFY-X owner:** `govern-runtime-protocol-deployment`

### `design-mcp-server-capability`

Design MCP tools, resources, and prompts with narrow schemas, explicit transport, validation, permission boundaries, deterministic outputs, and health checks.

**Use when:** an integration should become a reusable MCP surface; tool definitions are too broad or ambiguous; MCP lifecycle exists but implementation guidance is missing.

**Mechanisms:** tool/resource/prompt separation; schema validation; stdio or HTTP transport choice; capability discovery; health check; error recovery contract.

**Hard boundaries:** MCP exposure does not imply authorization; validate all external input; do not hide network side effects.

**Proposed PACIFY-X owner:** `manage-mcp-lifecycle`

## Admission requirements

- Validate behavioral need against the current PACIFY-X owner and semantic index.
- Prefer merging a mechanism into an existing owner over creating a competing control plane.
- Run negative, conflict, rollback, license, and retrieval tests.
- Keep all learned or external content candidate-only until explicit admission.

## Provenance

Sources: everything-claude-code. Everything Claude Code material is MIT licensed and preserved with attribution. HyperLearning-derived entries are clean-room mechanism abstractions only because no source license was found.
