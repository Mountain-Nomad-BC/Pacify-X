---
name: dynamic-skill-detonator
description: "Execute a skill in an instrumented sandbox with synthetic secrets and observe real behavior. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# dynamic-skill-detonator

## Purpose

Execute a skill in an instrumented sandbox with synthetic secrets and observe real behavior.

## Use when
- skill has code/dynamic instructions/dependencies/external calls

## Do not use when
- environment cannot isolate effects

## Required inputs
- package
- sandbox policy
- synthetic secrets
- network allowlist
- expected effects

## Outputs
- observed behavior
- data flows
- effect diff
- findings
- artifact log

## Procedure
1. build isolated env.
2. seed canaries.
3. run representative tests.
4. trace OS/network/process.
5. compare declared/observed.
6. retain evidence.

## Guardrails
- no live credentials.
- default-deny network.
- destroy sandbox.
- resource limits.

## Integration points
- skill admission
- container sandbox
- security evidence

## Failure modes to test
- sandbox mismatch
- dormant payload

## Operational metrics
- undeclared effects
- escape attempts
- coverage

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [SkillDetonate: Dynamic Analysis for Agent Skills](https://arxiv.org/abs/2607.02357)
- [Malicious Agent Skills in the Wild](https://arxiv.org/abs/2602.06547)

## Runtime binding

- Family: `supply_chain`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
