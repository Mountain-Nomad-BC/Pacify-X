---
name: benchmark-domain-adapter
description: "Translate an academic benchmark into independent framework domain cases, outcomes, risks, and evidence requirements. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# benchmark-domain-adapter

## Purpose

Translate an academic benchmark into independent framework domain cases, outcomes, risks, and evidence requirements.

## Use when
- claim needs validation on diagnostics/transcripts/RAG/code/operations

## Do not use when
- original benchmark already matches domain/data policy

## Required inputs
- paper benchmark
- domain taxonomy
- historical cases
- postconditions
- risk tiers

## Outputs
- domain benchmark
- case set
- rubric
- baseline
- acceptance threshold

## Procedure
1. identify tested construct.
2. map analogue.
3. preserve difficulty/failures.
4. add evidence/safety.
5. define baseline/statistics.

## Guardrails
- no easy-case cherry-picking.
- separate accuracy from consequence.
- protect sensitive data.

## Integration points
- active evaluation
- scenario audits
- certification

## Failure modes to test
- analogue changes construct
- historical leakage

## Operational metrics
- benchmark validity
- production correlation

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [ProEval: Proactive Failure Discovery](https://deepmind.google/research/publications/238239/)
- [Long-Horizon-Terminal-Bench](https://arxiv.org/abs/2607.08964)

## Runtime binding

- Family: `research`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
