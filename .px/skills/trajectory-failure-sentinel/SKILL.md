---
name: trajectory-failure-sentinel
description: "Detect failure onset early enough to recover before cost or state damage accumulates. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# trajectory-failure-sentinel

## Purpose

Detect failure onset early enough to recover before cost or state damage accumulates.

## Use when
- multi-step agent/pipeline active

## Do not use when
- single deterministic step

## Required inputs
- plan
- step events
- tool results
- state changes
- hypotheses
- cost
- failure signatures

## Outputs
- trajectory health
- onset step
- failure class
- recovery recommendation
- basis

## Procedure
1. compare expected/actual progress.
2. detect ignored evidence/no-ops.
3. detect unsupported commitment.
4. detect widening hypotheses.
5. estimate recoverability.
6. signal replan/escalation.

## Guardrails
- uncertainty alone is not failure.
- distinguish exploration from drift.
- record intervention evidence.

## Integration points
- turn orchestrator
- progress ledger
- recovery

## Failure modes to test
- hard reasoning interrupted
- signal after irreversible action

## Operational metrics
- lead time
- early recovery
- false intervention

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Failure as a Process](https://arxiv.org/abs/2607.09510)

## Runtime binding

- Family: `loop`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
