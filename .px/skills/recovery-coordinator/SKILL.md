---
name: recovery-coordinator
description: "Classify failures and choose retry, alternate path, rollback, escalation, or stop. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# recovery-coordinator

## Purpose

Classify failures and choose retry, alternate path, rollback, escalation, or stop.

## Use when
- execution/tool/policy/verification/persistence fails

## Do not use when
- policy violation requires stop
- irreversible effect lacks idempotency

## Required inputs
- failure class
- state
- trace
- retry budget
- fallbacks
- rollback capability

## Outputs
- recovery decision
- next state
- retry parameters
- rollback plan
- escalation packet

## Procedure
1. normalize failure.
2. determine retryability.
3. inspect attempts/state changes.
4. select distinct recovery path.
5. open circuit on repetition.
6. record next allowed state.

## Guardrails
- generic retry prohibited.
- never retry a denial by rephrasing.
- preserve forensic state.

## Integration points
- turn orchestrator
- tool gateway
- circuit breaker
- handoff

## Failure modes to test
- misclassification
- retry storm
- unsafe fallback

## Operational metrics
- recovery rate
- repeat failures
- rollback success
- attempts before escalation

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Loop Engineering Is Just Software Engineering](https://iii.dev/blog/loop-engineering-is-just-software-engineering/)
- [Failure as a Process](https://arxiv.org/abs/2607.09510)

## Runtime binding

- Family: `delegated`
- Binding: `runtime/recovery.py`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
