---
name: govern-hooked-execution
description: Treat hooks and agent configuration as governed, validated runtime supply-chain
  surfaces. Candidate external-intake bundle; keep inactive until PACIFY-X admission
  and owner review.
---

# Govern Hooked Execution

## Purpose

Treat hooks and agent configuration as governed, validated runtime supply-chain surfaces.

## Loading rule

Load this candidate metadata only after semantic selection. Load one capability reference at a time. Raw external source material is quarantined as reference-only and must never execute merely because it is present.

## Candidate capabilities

### `govern-agent-hook-lifecycle`

Register, profile, disable, validate, and observe pre/post action hooks as governed runtime controls rather than loose shell snippets.

**Use when:** tool calls need policy enforcement; format/type/test checks should run automatically; hook failures or loops are destabilizing sessions.

**Mechanisms:** hook profiles; disabled-hook allowlist; re-entrancy guard; config protection; preflight quality checks; post-action logging; health validation.

**Hard boundaries:** hooks may not silently broaden permissions; failing hooks must degrade predictably; no fragile inline shell when a script boundary is safer.

**Proposed PACIFY-X owner:** `supervise-contained-execution`

### `enforce-agent-config-supply-chain`

Scan agent instructions, hooks, MCP configuration, Unicode, paths, and generated projections for injection, secret, portability, and policy risks before installation or execution.

**Use when:** importing external agent configuration; hooks or MCP servers are being installed; cross-platform projection may carry unsafe paths.

**Mechanisms:** config security scan; Unicode safety; personal path detection; hook validation; MCP exposure review; quarantine disposition.

**Hard boundaries:** scanner output is evidence, not automatic guilt; never execute imported hooks during inspection; preserve source license and provenance.

**Proposed PACIFY-X owner:** `secure-agent-supply-chain`

## Admission requirements

- Validate behavioral need against the current PACIFY-X owner and semantic index.
- Prefer merging a mechanism into an existing owner over creating a competing control plane.
- Run negative, conflict, rollback, license, and retrieval tests.
- Keep all learned or external content candidate-only until explicit admission.

## Provenance

Sources: everything-claude-code. Everything Claude Code material is MIT licensed and preserved with attribution. HyperLearning-derived entries are clean-room mechanism abstractions only because no source license was found.
