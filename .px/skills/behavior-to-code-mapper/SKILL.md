---
name: behavior-to-code-mapper
description: "Map runtime behaviors to code, states, tools, policies, tests, telemetry, and dependencies. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# behavior-to-code-mapper

## Purpose

Map runtime behaviors to code, states, tools, policies, tests, telemetry, and dependencies.

## Use when
- behavior must be changed/audited/debugged
- harness logic is distributed

## Do not use when
- known isolated function needs no impact map

## Required inputs
- repositories
- AST/call graphs
- routes
- state machines
- manifests
- traces
- tests

## Outputs
- behavior graph
- source locations
- impact set
- coverage gaps
- handbook entries

## Procedure
1. extract deterministic code facts.
2. map events/transitions.
3. associate policies/manifests.
4. use LLM only for semantic grouping.
5. link tests/telemetry.
6. record confidence gaps.

## Guardrails
- generated prose cannot override code facts.
- version maps.
- flag drift.

## Integration points
- engineering companion
- Graphify
- Obsidian
- intelligent system registry
- test inventory

## Failure modes to test
- dynamic dispatch missed
- ownership confusion
- map not refreshed

## Operational metrics
- mapping coverage
- impact precision
- stale edges
- time to locate

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
