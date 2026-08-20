---
name: active-evaluation-selector
description: "Choose the most informative evaluation cases under fixed time, compute, or review budget. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# active-evaluation-selector

## Purpose

Choose the most informative evaluation cases under fixed time, compute, or review budget.

## Use when
- model/skill/retrieval/policy/workflow changes need evaluation

## Do not use when
- mandatory certification suite must run fully

## Required inputs
- candidate cases
- change impact
- uncertainty
- failure history
- risk
- budget

## Outputs
- ranked cases
- rationale
- coverage estimate
- residual risk

## Procedure
1. include golden cases.
2. score impact/risk.
3. prioritize disagreement/boundaries.
4. maximize diversity.
5. reserve exploration quota.
6. track failure clusters.
7. union the bounded ranked set with every mandatory test selected by changed-area ownership, contract, migration, security, persistence, and deployment policy.
8. report selected and unselected denominators separately; budget selection may optimize optional evidence but never omit a mandatory certification check.

## Guardrails
- not only model uncertainty.
- retain stable benchmarks.
- record bias.

## Integration points
- intelligent system evaluation
- impact tracer
- trajectory sentinel

## Failure modes to test
- known-failure overfit
- rare severe under-sampling

## Operational metrics
- failures per 100
- changed-path coverage
- cost
- missed regressions

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [ProEval: Proactive Failure Discovery](https://deepmind.google/research/publications/238239/)

## Runtime binding

- Family: `evaluation`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
