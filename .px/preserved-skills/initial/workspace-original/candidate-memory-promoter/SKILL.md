---
name: candidate-memory-promoter
description: "Decide whether a trace-derived observation, claim, or procedure may enter a wider memory scope. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# candidate-memory-promoter

## Purpose

Decide whether a trace-derived observation, claim, or procedure may enter a wider memory scope.

## Use when
- completed run proposes memory

## Do not use when
- run unverified/disputed/policy-violating

## Required inputs
- candidate
- source evidence
- verification
- scope
- contradictions
- owner
- expiry

## Outputs
- promote/reject/quarantine
- target scope
- requirements
- supersession links

## Procedure
1. validate provenance.
2. classify candidate.
3. check evidence/verification.
4. search contradictions/duplicates.
5. apply scope/retention.
6. record decision.

## Guardrails
- intelligent system proposes but does not self-promote.
- claims need sources.
- procedures need replay/security/canary.

## Integration points
- intelligent system memory governance
- outcome verifier
- knowledge graph
- promotion

## Failure modes to test
- weak evidence promoted
- missed contradiction
- over-broad scope

## Operational metrics
- correction rate
- duplicates
- stale claims

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Andrej Karpathy LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [LLM Wiki v2](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2)
- [MemHarness: Memory Is Reconstructed, Not Replayed](https://arxiv.org/abs/2607.28272)

## Runtime binding

- Family: `memory`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
