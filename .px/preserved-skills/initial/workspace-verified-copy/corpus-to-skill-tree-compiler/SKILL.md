---
name: corpus-to-skill-tree-compiler
description: "Compile large corpora into navigable hierarchical skill/knowledge trees with evidence-linked nodes. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# corpus-to-skill-tree-compiler

## Purpose

Compile large corpora into navigable hierarchical skill/knowledge trees with evidence-linked nodes.

## Use when
- knowledge spans many documents
- flat retrieval loses structure

## Do not use when
- tiny corpus or deterministic lookup exists

## Required inputs
- documents
- canonical taxonomy
- model/product mappings
- evidence IDs
- access scopes

## Outputs
- navigation tree
- node summaries
- evidence links
- cross-branch relations
- drift report

## Procedure
1. ingest/classify.
2. align taxonomy.
3. create nodes.
4. attach evidence/scope.
5. validate tasks.
6. monitor drift.

## Guardrails
- nodes are not unsupported facts.
- preserve originals.
- enforce access.

## Integration points
- TurnBurn graph
- intelligent system RAG
- skill navigator
- LMS source library

## Failure modes to test
- wrong hierarchy
- summary drift

## Operational metrics
- navigation success
- evidence precision
- context reduction

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Don't Retrieve, Navigate: Distilling Enterprise Knowledge](https://arxiv.org/abs/2604.14572)
- [Andrej Karpathy LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

## Runtime binding

- Family: `compile`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
