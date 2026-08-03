---
name: cross-paper-mechanism-fuser
description: "Combine compatible research primitives into a stronger subsystem while exposing conflicts. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# cross-paper-mechanism-fuser

## Purpose

Combine compatible research primitives into a stronger subsystem while exposing conflicts.

## Use when
- mechanisms address adjacent workflow parts

## Do not use when
- complexity rises without measurable gain

## Required inputs
- mechanism cards
- assumptions
- data flows
- controls
- architecture

## Outputs
- fused architecture
- interaction risks
- shared components
- test matrix
- phases

## Procedure
1. align contracts/assumptions.
2. identify reinforcement/conflict.
3. assign one owner.
4. design shared evidence/telemetry.
5. test separate and combined.

## Guardrails
- do not create feature pile.
- preserve independent boundaries.
- measure marginal value.

## Integration points
- research registry
- decision log

## Failure modes to test
- optimizers fight
- shared data correlates errors

## Operational metrics
- combined lift
- complexity cost
- interaction failures

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [MemHarness: Memory Is Reconstructed, Not Replayed](https://arxiv.org/abs/2607.28272)
- [MIND: Memory Injection Defense](https://arxiv.org/abs/2607.28103)
- [Tools Are Not Islands: Set-Level Tool Retrieval](https://arxiv.org/abs/2607.25718)
- [ProEval: Proactive Failure Discovery](https://deepmind.google/research/publications/238239/)

## Runtime binding

- Family: `research`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
