---
name: long-horizon-progress-ledger
description: "Represent long work as evidence-backed milestones with partial completion, blockers, regression, and recoverability. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# long-horizon-progress-ledger

## Purpose

Represent long work as evidence-backed milestones with partial completion, blockers, regression, and recoverability.

## Use when
- work spans many steps/sessions/agents/hours

## Do not use when
- atomic task

## Required inputs
- goal
- milestones
- events
- evidence
- budgets
- owners

## Outputs
- milestone status
- partial score
- blockers
- resume point
- remaining risk

## Procedure
1. decompose into verifiable milestones.
2. attach evidence.
3. update from events.
4. record regression/blockers.
5. compute recoverability.
6. checkpoint.

## Guardrails
- completion requires evidence.
- file creation is not correctness.
- preserve ownership/dependencies.

## Integration points
- intelligent system task store
- handoff
- trajectory sentinel
- UI

## Failure modes to test
- activity milestones
- manual burden

## Operational metrics
- resume success
- late recovery
- false completion

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Long-Horizon-Terminal-Bench](https://arxiv.org/abs/2607.08964)

## Runtime binding

- Family: `progress`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
