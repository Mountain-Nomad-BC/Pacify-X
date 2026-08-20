---
name: reasoning-utility-controller
description: "Decide whether another reasoning, retrieval, verification, or tool step has enough expected value. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# reasoning-utility-controller

## Purpose

Decide whether another reasoning, retrieval, verification, or tool step has enough expected value.

## Use when
- loop may continue
- budget/latency matters
- verification repeats

## Do not use when
- mandatory safety check remains

## Required inputs
- information gain
- unresolved requirements
- state change
- repetition
- cost
- risk
- budget

## Outputs
- continue/stop/escalate
- utility
- reason
- next permitted action

## Procedure
1. measure information gain.
2. measure hypothesis reduction.
3. detect repeated patterns.
4. estimate decision impact.
5. compare value/cost/risk.
6. stop/escalate when utility collapses.

## Guardrails
- mandatory postconditions remain.
- token length alone is not decision.
- loop opens circuit.

## Integration points
- budget controller
- tool-loop breaker
- planner

## Failure modes to test
- bad utility calibration
- important cheap check skipped

## Operational metrics
- cost per outcome
- unnecessary calls
- premature stops

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Towards Structural Understanding of LLM Overthinking](https://deepmind.google/research/publications/203490/)
- [Tool-Induced Cyclic Execution Research](https://arxiv.org/abs/2602.14798)

## Runtime binding

- Family: `loop`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
