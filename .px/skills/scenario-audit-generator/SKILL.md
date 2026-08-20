---
name: scenario-audit-generator
description: "Generate realistic pressure, injection, stale-data, conflict, permission, and deception scenarios. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# scenario-audit-generator

## Purpose

Generate realistic pressure, injection, stale-data, conflict, permission, and deception scenarios.

## Use when
- capability/model/policy/tool promoted
- security gap suspected

## Do not use when
- live sensitive data or uncontrolled effects required

## Required inputs
- capability map
- risk model
- incident history
- policy
- tool effects
- data classes

## Outputs
- versioned scenarios
- invariants
- rubric
- fixtures
- coverage

## Procedure
1. identify pressure points.
2. generate realistic variations.
3. define invariants.
4. sandbox effects.
5. run versions.
6. cluster failures into regressions.

## Guardrails
- avoid sensational threats.
- test controls not intentions.
- keep reproducible.

## Integration points
- intelligent system evaluation
- security testing
- skill detonation
- CI

## Failure modes to test
- unrealistic scenarios
- rubric rewards refusal

## Operational metrics
- unique failures
- reproducibility
- regression recurrence

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Gram: Automated Alignment Auditing](https://deepmind.google/research/publications/252981/)
- [Realistic Honeypot Evaluations](https://deepmind.google/research/publications/253391/)

## Runtime binding

- Family: `evaluation`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
