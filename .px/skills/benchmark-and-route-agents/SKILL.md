---
name: benchmark-and-route-agents
description: Benchmark agent behavior and route models using evidence, reliability,
  and economic constraints. Candidate external-intake bundle; keep inactive until
  PACIFY-X admission and owner review.
---

# Benchmark And Route Agents

## Purpose

Benchmark agent behavior and route models using evidence, reliability, and economic constraints.

## Loading rule

Load this candidate metadata only after semantic selection. Load one capability reference at a time. Raw external source material is quarantined as reference-only and must never execute merely because it is present.

## Candidate capabilities

### `benchmark-agent-regressions`

Run repeatable task suites across agents, models, prompts, or harness versions and compare pass rate, pass@k, cost, time, consistency, and failure class.

**Use when:** a model or harness upgrade may regress behavior; routing decisions need empirical evidence; skills claim compliance without behavior proof.

**Mechanisms:** sandboxed task fixtures; head-to-head runs; pass@k; cost/time accounting; consistency variance; behavioral compliance scenarios.

**Hard boundaries:** benchmark tasks must not touch production; do not optimize only for one visible fixture; retain failed traces and variance.

**Proposed PACIFY-X owner:** `engineer-verification-lab`

### `govern-model-routing-economics`

Select models by task complexity, required reliability, privacy, latency, and budget using measured evidence, bounded retries, and prompt-cache awareness.

**Use when:** not every task requires the largest model; routing must balance cost and success probability; fallbacks currently retry blindly.

**Mechanisms:** task complexity bands; budget envelope; fallback ladder; retry economics; prompt caching; cost per successful task.

**Hard boundaries:** cost cannot override safety or required quality; routing confidence must be observable; no vendor lock-in in the canonical policy.

**Proposed PACIFY-X owner:** `reasoning-utility-controller`

## Admission requirements

- Validate behavioral need against the current PACIFY-X owner and semantic index.
- Prefer merging a mechanism into an existing owner over creating a competing control plane.
- Run negative, conflict, rollback, license, and retrieval tests.
- Keep all learned or external content candidate-only until explicit admission.

## Provenance

Sources: everything-claude-code. Everything Claude Code material is MIT licensed and preserved with attribution. HyperLearning-derived entries are clean-room mechanism abstractions only because no source license was found.
