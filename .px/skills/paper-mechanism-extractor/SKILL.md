---
name: paper-mechanism-extractor
description: "Extract the actual mechanism, assumptions, data, evidence, and limitations from a paper. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# paper-mechanism-extractor

## Purpose

Extract the actual mechanism, assumptions, data, evidence, and limitations from a paper.

## Use when
- new paper considered

## Do not use when
- primary source is available but only summary was read

## Required inputs
- paper
- supplement
- code
- claims
- related work

## Outputs
- mechanism card
- claim/evidence map
- assumptions
- limitations
- reproduction requirements

## Procedure
1. identify problem/baseline.
2. extract primitive.
3. separate evidence from interpretation.
4. record datasets/metrics.
5. identify operational gaps.

## Guardrails
- primary source first.
- benchmark gain is not production gain.
- preserve attribution.

## Integration points
- research registry
- gap analyzer

## Failure modes to test
- abstract mistaken for method
- evaluation leakage missed

## Operational metrics
- claim accuracy
- missing assumptions

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [arXiv cs.AI recent](https://arxiv.org/list/cs.AI/recent)
- [VoltAgent Awesome AI Agent Papers](https://github.com/VoltAgent/awesome-ai-agent-papers)

## Runtime binding

- Family: `research`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
