---
name: execution-contract-enforcer
description: "Wrap every skill with validation, authorization, budget, idempotency, execution, verification, and trace controls. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# execution-contract-enforcer

## Purpose

Wrap every skill with validation, authorization, budget, idempotency, execution, verification, and trace controls.

## Use when
- any governed skill executes

## Do not use when
- never bypass in production

## Required inputs
- execution envelope
- manifest
- identity
- policy decision
- approved context

## Outputs
- structured result
- trace events
- verification request
- memory candidates
- failure class

## Procedure
1. validate input/manifest.
2. check scope/effects/risk.
3. reserve budget and idempotency.
4. execute in declared environment.
5. validate output.
6. verify postconditions.
7. emit outcome.
8. reconcile budget.

## Guardrails
- permissions enforced outside model.
- error-specific retries.
- side effects need idempotency.
- memory writes remain candidates.

## Integration points
- intelligent system turn orchestrator
- policy engine
- tool gateway
- verifier
- telemetry

## Failure modes to test
- wrapper becomes monolith
- unsafe retry class
- vague postconditions

## Operational metrics
- schema failures
- duplicate effects prevented
- unclassified errors
- bypass attempts

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [How to Build Your Own Agent Harness](https://iii.dev/blog/how-to-build-your-own-agent-harness/)
- [Loop Engineering Is Just Software Engineering](https://iii.dev/blog/loop-engineering-is-just-software-engineering/)
- [Graph-Based Agentic AI with LangGraph](https://arxiv.org/abs/2607.19297)

## Runtime binding

- Family: `delegated`
- Binding: `runtime/execution_contract.py`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
