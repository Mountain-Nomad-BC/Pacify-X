---
name: skill-bundle-resolver
description: "Select a compatible set of skills and tools that jointly satisfies all required outcomes. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# skill-bundle-resolver

## Purpose

Select a compatible set of skills and tools that jointly satisfies all required outcomes.

## Use when
- task needs multiple capabilities
- one skill cannot satisfy all postconditions
- co-execution data exists

## Do not use when
- single deterministic tool call
- required capabilities have incompatible effects

## Required inputs
- candidate skills
- required capability slots
- dependency graph
- co-execution graph
- risk/cost/latency limits

## Outputs
- ranked bundles
- execution order
- compatibility warnings
- fallback bundle

## Procedure
1. derive capability slots.
2. construct bundles.
3. reject incompatible versions/permissions.
4. score coverage/success/risk/cost.
5. attach verifier and recovery.
6. return smallest complete bundle.

## Guardrails
- never drop safety for cost.
- do not infer compatibility from text alone.
- sequence side effects explicitly.

## Integration points
- skill registry
- coexecution graph
- planner
- framework policy

## Failure modes to test
- sparse history bias
- correlation treated as causality
- version drift

## Operational metrics
- complete-bundle rate
- missing-tool failures
- unnecessary skills
- cost per verified outcome

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Tools Are Not Islands: Set-Level Tool Retrieval](https://arxiv.org/abs/2607.25718)

## Runtime binding

- Family: `bundle`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
