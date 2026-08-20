---
name: memory-applicability-critic
description: "Determine which parts of a retrieved case apply now and which must be rejected. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# memory-applicability-critic

## Purpose

Determine which parts of a retrieved case apply now and which must be rejected.

## Use when
- episodic/procedural memory retrieved
- prior case seems similar

## Do not use when
- item is current immutable evidence or approved policy

## Required inputs
- current context
- memory
- scope metadata
- model/firmware/time variables
- evidence quality

## Outputs
- matching conditions
- mismatches
- missing information
- reusable principles
- prohibited replay

## Procedure
1. compare material variables.
2. assess source/outcome quality.
3. separate principle from old action.
4. list missing evidence.
5. assign applicability.

## Guardrails
- similar symptom is insufficient.
- replacement action is not a fact.
- current evidence overrides precedent.

## Integration points
- intelligent system memory
- experience reconstructor
- diagnostic planner

## Failure modes to test
- version difference missed
- over-filtering

## Operational metrics
- negative transfer
- rejection precision
- human corrections

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [MemHarness: Memory Is Reconstructed, Not Replayed](https://arxiv.org/abs/2607.28272)

## Runtime binding

- Family: `memory`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
