---
name: skill-coexecution-graph-builder
description: "Build a typed graph of skills/tools used together, order, context, outcomes, cost, and latency. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# skill-coexecution-graph-builder

## Purpose

Build a typed graph of skills/tools used together, order, context, outcomes, cost, and latency.

## Use when
- traces identify versions/outcomes

## Do not use when
- trace quality too low

## Required inputs
- execution traces
- versions
- context features
- outcomes
- cost/latency

## Outputs
- coexecution graph
- sequence patterns
- conditional success
- incompatibilities

## Procedure
1. normalize identities.
2. create typed nodes/hyperedges.
3. attach context/outcomes.
4. separate correlation/dependency.
5. expire stale versions.

## Guardrails
- frequent co-use is not required dependency.
- protect context features.
- version edges.

## Integration points
- bundle resolver
- graph store
- evaluation

## Failure modes to test
- popular workflow dominates
- version mixing

## Operational metrics
- bundle lift
- stale edges
- trace coverage

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Tools Are Not Islands: Set-Level Tool Retrieval](https://arxiv.org/abs/2607.25718)

## Runtime binding

- Family: `impact`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
