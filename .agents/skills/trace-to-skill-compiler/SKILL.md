---
name: trace-to-skill-compiler
description: "Convert repeated verified trajectories into candidate governed skill packages. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# trace-to-skill-compiler

## Purpose

Convert repeated verified trajectories into candidate governed skill packages.

## Use when
- stable repeated procedure has success and failure examples

## Do not use when
- outcomes unverified
- hidden human judgment not represented

## Required inputs
- traces
- outcomes
- evidence
- failures
- domain variables
- existing skills

## Outputs
- draft SKILL.md
- manifest
- conditions
- tests
- limitations

## Procedure
1. Normalize successful and failed traces into `contracts/engineering-process-record.schema.json`; reject unverified outcomes or recoveries.
2. Preserve why each decision and tool was chosen, including alternatives and effects.
3. Run `engineering-bootstrap process compile --record <record.json>` to derive decision, tool, and execution graphs.
4. Identify invariant steps, branches, activation, termination, recovery, and evidence requirements.
5. Compare against existing skills before drafting; prefer an evidenced improvement over a duplicate skill.
6. Generate positive, negative, recovery, effect-boundary, and termination tests.
7. Submit the inert result through the skill admission controller; never activate from a trace alone.

## Guardrails
- no auto-promotion.
- detect overlap.
- domain review.

## Integration points
- procedural compiler
- skill admission
- research translator

## Failure modes to test
- bad practice compiled
- too specific/broad

## Operational metrics
- accepted drafts
- regression success
- duplicates avoided

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [ProcMEM: Learning Reusable Procedural Memory](https://arxiv.org/abs/2602.01869)

## Runtime binding

- Family: `compile`
- Binding: `runtime.process_memory.compile_process_candidate`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
