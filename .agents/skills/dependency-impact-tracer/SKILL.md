---
name: dependency-impact-tracer
description: "Predict downstream effects of changing a skill, tool, schema, state, model, policy, or data contract. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# dependency-impact-tracer

## Purpose

Predict downstream effects of changing a skill, tool, schema, state, model, policy, or data contract.

## Use when
- component change proposed
- deprecation or migration planned

## Do not use when
- documentation-only change has no executable effect

## Required inputs
- behavior graph
- dependency graph
- registry refs
- tests
- telemetry consumers
- versions

## Outputs
- affected components
- required tests
- migration steps
- risk
- rollback dependencies

## Procedure
1. locate changed node.
2. traverse typed dependencies.
3. separate code/runtime/data/policy effects.
4. map tests/dashboards.
5. rank consequence/confidence.
6. emit changed-area validation selectors covering owners, direct and transitive consumers, contracts, migrations, routes, persistence, deployment assets, and prior failure clusters.
7. keep unknown dynamic edges in the mandatory review denominator; absence from the graph is not proof of no impact.

## Guardrails
- not all edges are equal.
- include trace-discovered consumers.
- flag unknown dynamic links.

## Integration points
- behavior mapper
- registries
- CI gates
- promotion

## Failure modes to test
- incomplete graph
- stale registry
- unmapped dynamic integration

## Operational metrics
- escaped impact defects
- false positives
- test selection accuracy

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Harness Handbook](https://arxiv.org/abs/2607.13285)

## Runtime binding

- Family: `impact`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
