---
name: bounded-workflow-topology-selector
description: "Select among approved workflow templates based on complexity, novelty, risk, and evidence conflict. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# bounded-workflow-topology-selector

## Purpose

Select among approved workflow templates based on complexity, novelty, risk, and evidence conflict.

## Use when
- multiple validated topologies exist

## Do not use when
- would invent arbitrary roles/links in production

## Required inputs
- task class
- risk
- novelty
- specialists
- performance history

## Outputs
- template
- roles
- visibility
- verification path
- fallback

## Procedure
1. classify task/risk.
2. filter templates by policy.
3. score performance/cost.
4. select least complex sufficient.
5. switch only on approved triggers.

## Guardrails
- prevalidated templates.
- fixed authority.
- trace changes.

## Integration points
- workflow router
- planner
- outcome verifier

## Failure modes to test
- benchmark overfit
- coordination cost

## Operational metrics
- success by topology
- cost vs baseline
- switches

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [MANTA: Multi-Agent Network Topology Adaptation](https://arxiv.org/abs/2607.28527)

## Runtime binding

- Family: `topology`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
