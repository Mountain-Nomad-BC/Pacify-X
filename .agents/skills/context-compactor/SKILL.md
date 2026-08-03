---
name: context-compactor
description: "Reduce active context while preserving goals, constraints, decisions, evidence, unresolved questions, and state. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# context-compactor

## Purpose

Reduce active context while preserving goals, constraints, decisions, evidence, unresolved questions, and state.

## Use when
- context approaches budget
- long run crosses checkpoint
- branches merge

## Do not use when
- evidence can remain by reference
- required records would be discarded

## Required inputs
- events/conversation
- state
- evidence refs
- decision log
- unresolved requirements

## Outputs
- compact state
- preserved refs
- discard index
- compaction confidence

## Procedure
1. extract facts/constraints.
2. preserve decisions.
3. preserve unresolved items.
4. replace bulky evidence with refs.
5. mark omissions.
6. validate against state.

## Guardrails
- do not turn hypotheses into facts.
- never remove negative constraints.
- retain originals.

## Integration points
- session store
- context assembler
- checkpoint service

## Failure modes to test
- semantic drift
- negative constraint loss
- staleness

## Operational metrics
- token reduction
- reconstruction accuracy
- lost constraints
- corrections

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [How to Build Your Own Agent Harness](https://iii.dev/blog/how-to-build-your-own-agent-harness/)

## Runtime binding

- Family: `delegated`
- Binding: `runtime/startup.py`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
