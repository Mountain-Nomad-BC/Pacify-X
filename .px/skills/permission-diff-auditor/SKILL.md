---
name: permission-diff-auditor
description: "Identify new permissions, scopes, side effects, and destinations between versions. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# permission-diff-auditor

## Purpose

Identify new permissions, scopes, side effects, and destinations between versions.

## Use when
- skill/dependency changes

## Do not use when
- no executable or permission-bearing change

## Required inputs
- old package
- new package
- observed effects

## Outputs
- permission diff
- risk delta
- approval requirement
- compatibility warning

## Procedure
1. normalize permissions.
2. diff data/tool scopes.
3. diff effect class.
4. compare observed behavior.
5. calculate risk change.
6. require approval for expansion.

## Guardrails
- dependency expansion cannot hide.
- also test removals for breakage.

## Integration points
- admission
- impact tracer
- framework policy

## Failure modes to test
- semantic equivalence noise
- dynamic effect missed

## Operational metrics
- unapproved expansion
- dependency expansion found

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Malicious Agent Skills in the Wild](https://arxiv.org/abs/2602.06547)

## Runtime binding

- Family: `supply_chain`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
