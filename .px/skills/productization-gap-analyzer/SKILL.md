---
name: productization-gap-analyzer
description: "Identify what a research prototype lacks before safe operational use. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# productization-gap-analyzer

## Purpose

Identify what a research prototype lacks before safe operational use.

## Use when
- mechanism useful but immature

## Do not use when
- mature internal component already covers it

## Required inputs
- mechanism card
- available code
- existing architecture
- security/SRE requirements

## Outputs
- gap list
- MVP approximation
- full path
- build/buy/reject recommendation

## Procedure
1. compare internal coverage.
2. identify missing state/API/security/tests/observability/rollback.
3. design simpler approximation.
4. estimate value/risk.

## Guardrails
- do not rebuild for novelty.
- prefer deterministic scaffolding.
- record rejected duplication.

## Integration points
- behavior map
- architecture registry
- research translator

## Failure modes to test
- data requirements underestimated
- assumptions do not transfer

## Operational metrics
- duplicate builds avoided
- paper-to-MVP time

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Harness Handbook](https://arxiv.org/abs/2607.13285)
- [How to Build Your Own Agent Harness](https://iii.dev/blog/how-to-build-your-own-agent-harness/)

## Runtime binding

- Family: `research`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
