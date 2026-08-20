---
name: evidence-assembler
description: "Build a typed evidence package distinguishing measurement, source text, tool output, inference, assumption, and precedent. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# evidence-assembler

## Purpose

Build a typed evidence package distinguishing measurement, source text, tool output, inference, assumption, and precedent.

## Use when
- factual conclusion/diagnostic/verifier request produced

## Do not use when
- purely creative output

## Required inputs
- claims
- measurements
- documents
- tool results
- memory precedents
- timestamps

## Outputs
- claim-evidence graph
- sufficiency
- freshness warnings
- unsupported claims

## Procedure
1. enumerate claims.
2. attach direct sources.
3. classify evidence type.
4. record freshness/scope.
5. mark inference.
6. flag unsupported/contradictory.
7. bind the package to exact input, implementation, registry, artifact, and evidence-index hashes.
8. publish complete pass/fail/blocked/skipped/uncertain denominators and the tools actually invoked; never infer execution from a planned command or an output filename.

## Guardrails
- label assumptions.
- history is not direct evidence.
- citations must resolve.
- an executor cannot self-certify its own completion claim.
- unexecuted or missing evidence remains missing even when adjacent checks pass.

## Integration points
- intelligent system retrieval/citation
- outcome verifier
- diagnostic reports
- knowledge graph

## Failure modes to test
- weak source treated authoritative
- out-of-scope evidence

## Operational metrics
- unsupported claims
- citation resolution
- human corrections

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Andrej Karpathy LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [MemHarness: Memory Is Reconstructed, Not Replayed](https://arxiv.org/abs/2607.28272)

## Runtime binding

- Family: `delegated`
- Binding: `runtime/evidence_assembler.py`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
