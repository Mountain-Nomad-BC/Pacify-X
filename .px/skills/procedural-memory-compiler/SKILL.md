---
name: procedural-memory-compiler
description: "Compile repeated successful patterns into candidate procedures with activation, execution, and termination. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# procedural-memory-compiler

## Purpose

Compile repeated successful patterns into candidate procedures with activation, execution, and termination.

## Use when
- multiple verified traces share stable success

## Do not use when
- traces sparse/contradictory/unverified

## Required inputs
- successful traces
- failure traces
- domain variables
- approved skills
- outcomes

## Outputs
- candidate procedure
- activation
- steps
- termination
- exceptions
- tests

## Procedure
1. Require a verified engineering process record conforming to `contracts/engineering-process-record.schema.json`.
2. Preserve goal, decision reasons and alternatives, tool-selection reasons and effects, ordered steps, failures, recovery, verification, and evidence.
3. Run `engineering-bootstrap process compile --record <record.json>` to build decision, tool, and execution graphs.
4. Separate required actions from incidental trace details and compare the result with the current skill catalog.
5. Improve the closest existing skill when overlap is material; otherwise emit a new candidate.
6. Test activation, success, failure, recovery, and termination before submitting the inert candidate to admission.

## Guardrails
- no automatic activation; compilation always ends at candidate admission.
- domain owner review.
- frequency does not prove correctness.

## Integration points
- trace-to-skill compiler
- intelligent system improvement
- skill registry

## Failure modes to test
- bad habit compiled
- conditions too broad

## Operational metrics
- replay success
- edge failures
- human acceptance

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [ProcMEM: Learning Reusable Procedural Memory](https://arxiv.org/abs/2602.01869)

## Runtime binding

- Family: `compile`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
