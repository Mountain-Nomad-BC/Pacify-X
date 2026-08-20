---
name: tool-loop-circuit-breaker
description: "Detect cyclic tool calls, repeated no-op state, and cost amplification, then stop or isolate. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# tool-loop-circuit-breaker

## Purpose

Detect cyclic tool calls, repeated no-op state, and cost amplification, then stop or isolate.

## Use when
- agent executes multiple tools/retries

## Do not use when
- bounded polling loop stays within declared policy

## Required inputs
- tool sequence
- arguments
- results
- state hashes
- cost
- loop policy

## Outputs
- continue/open/review
- cycle signature
- waste estimate
- recovery state

## Procedure
1. normalize/hash calls.
2. detect repeating subsequences.
3. measure state/info change.
4. compare bounds.
5. open on zero progress.

## Guardrails
- not token count alone.
- preserve trace.
- lower thresholds for effects.

## Integration points
- utility controller
- tool gateway
- budget controller

## Failure modes to test
- small argument variation evades
- legitimate iteration stopped

## Operational metrics
- loops stopped
- cost saved
- false opens

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Tool-Induced Cyclic Execution Research](https://arxiv.org/abs/2602.14798)
- [Towards Structural Understanding of LLM Overthinking](https://deepmind.google/research/publications/203490/)

## Runtime binding

- Family: `loop`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
