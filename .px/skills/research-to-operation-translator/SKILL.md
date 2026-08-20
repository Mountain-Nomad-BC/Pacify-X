---
name: research-to-operation-translator
description: "Convert a validated research mechanism into a bounded skill, service, workflow, or evaluation. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# research-to-operation-translator

## Purpose

Convert a validated research mechanism into a bounded skill, service, workflow, or evaluation.

## Use when
- mechanism and gap show internal value

## Do not use when
- value unmeasurable or controls unavailable

## Required inputs
- mechanism card
- gap analysis
- target workflow
- data
- risk model

## Outputs
- operationalization canvas
- component architecture
- skills
- experiment
- promotion gates

## Procedure
1. define target operation.
2. choose value-preserving MVP.
3. map data/integrations.
4. define controls/verifier.
5. define domain benchmark.
6. plan canary/rollback.

## Guardrails
- no adoption without domain evidence.
- separate research fidelity from operational utility.
- retain source.

## Integration points
- intelligent system builders
- skill compiler
- evaluation

## Failure modes to test
- benchmark overfit
- MVP removes key mechanism

## Operational metrics
- measured value
- maintenance
- incidents
- rollback time

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [ProEval: Proactive Failure Discovery](https://deepmind.google/research/publications/238239/)
- [Harness Handbook](https://arxiv.org/abs/2607.13285)

## Runtime binding

- Family: `research`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
