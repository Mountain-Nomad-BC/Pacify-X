---
name: evaluation-budget-allocator
description: "Allocate automated and human review by risk, disagreement, novelty, impact, and evidence quality\u2014not self-confidence. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# evaluation-budget-allocator

## Purpose

Allocate automated and human review by risk, disagreement, novelty, impact, and evidence quality—not self-confidence.

## Use when
- many runs/changes compete for review

## Do not use when
- policy requires full review

## Required inputs
- risk tier
- impact
- verifier disagreement
- failure history
- novelty
- budget

## Outputs
- review allocation
- sampling plan
- residual risk
- thresholds

## Procedure
1. reserve mandatory review.
2. score structural risk/evidence.
3. discount correlated confidence.
4. allocate active cases.
5. track reviewer value.

## Guardrails
- confidence is not primary ranker.
- retain rare high-consequence quota.

## Integration points
- active selector
- review queue
- outcome verifier

## Failure modes to test
- risk drift
- correlated errors underestimated

## Operational metrics
- failures per review hour
- high-risk miss
- reviewer overload

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [One Human, N Agents: Audit-Budget Allocation](https://arxiv.org/abs/2607.28317)
- [ProEval: Proactive Failure Discovery](https://deepmind.google/research/publications/238239/)

## Runtime binding

- Family: `evaluation`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
