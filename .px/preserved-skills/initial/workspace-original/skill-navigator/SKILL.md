---
name: skill-navigator
description: "Progressively locate the smallest relevant capability branch without loading the full catalog. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# skill-navigator

## Purpose

Progressively locate the smallest relevant capability branch without loading the full catalog.

## Use when
- goal maps to multiple domains
- registry exceeds context budget
- aliases or product taxonomy must be resolved

## Do not use when
- exact approved skill ID/version is supplied
- caller cannot enumerate the branch

## Required inputs
- goal
- identity/scope
- capability index
- taxonomy aliases
- prior failures

## Outputs
- ranked path
- candidate skills
- missing information
- retrieval trace

## Procedure
1. normalize goal without erasing domain terms.
2. resolve canonical aliases.
3. score top-level branches.
4. expand only leading branches.
5. stop at manifest-level specificity.
6. return reasons and ambiguity.

## Guardrails
- never dump the full registry.
- filter access at every level.
- trace branch expansion.

## Integration points
- intelligent system registry
- planner
- taxonomy/navigation
- Corpus2Skill tree

## Failure modes to test
- bad taxonomy routing
- alias collision
- over-pruning

## Operational metrics
- candidate recall
- context loaded
- selection support
- unauthorized discovery

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Harness Handbook](https://arxiv.org/abs/2607.13285)
- [Don't Retrieve, Navigate: Distilling Enterprise Knowledge](https://arxiv.org/abs/2604.14572)

## Runtime binding

- Family: `delegated`
- Binding: `runtime/skill_navigator.py`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
