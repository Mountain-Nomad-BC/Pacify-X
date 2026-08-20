---
name: read-only-speculation-controller
description: "Predict and prefetch likely next read-only tool results into a quarantined cache. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# read-only-speculation-controller

## Purpose

Predict and prefetch likely next read-only tool results into a quarantined cache.

## Use when
- next read predictable
- call read-only/cacheable/low sensitivity/bounded cost

## Do not use when
- state-changing/approval/secrets/broad sensitive read
- low expected value

## Required inputs
- partial trajectory
- candidate tools
- predictor
- cost/sensitivity

## Outputs
- prefetch decision
- quarantined result
- waste record
- match event

## Procedure
1. classify effect/sensitivity.
2. predict call.
3. estimate net value.
4. execute to quarantine.
5. release only on actual match.

## Guardrails
- no speculative writes.
- do not inject unmatched results.
- measure waste/exposure.

## Integration points
- tool gateway
- cache
- budget controller

## Failure modes to test
- unneeded sensitive reads
- stale result

## Operational metrics
- latency saved
- hit rate
- waste cost
- data volume

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Speculate While You Reason](https://arxiv.org/abs/2607.25816)

## Runtime binding

- Family: `topology`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
