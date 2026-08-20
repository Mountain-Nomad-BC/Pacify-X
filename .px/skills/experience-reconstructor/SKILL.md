---
name: experience-reconstructor
description: "Rebuild a current procedure from reusable principles rather than replaying old actions. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# experience-reconstructor

## Purpose

Rebuild a current procedure from reusable principles rather than replaying old actions.

## Use when
- applicability critic finds partial value

## Do not use when
- approved deterministic procedure fully covers task

## Required inputs
- applicability analysis
- current evidence
- approved skills
- constraints
- postconditions

## Outputs
- adapted plan
- required evidence
- explicit exclusions
- verification plan

## Procedure
1. extract principles.
2. replace old assumptions with checks.
3. compose approved skills.
4. add missing measurements.
5. define termination/verification.

## Guardrails
- never copy historical conclusion.
- preserve provenance.
- mark adaptations.

## Integration points
- planner
- procedural memory
- outcome verifier

## Failure modes to test
- free-form invention
- silent assumptions

## Operational metrics
- adapted-plan success
- old-action replay
- evidence completeness

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [MemHarness: Memory Is Reconstructed, Not Replayed](https://arxiv.org/abs/2607.28272)
- [ProcMEM: Learning Reusable Procedural Memory](https://arxiv.org/abs/2602.01869)

## Runtime binding

- Family: `memory`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
