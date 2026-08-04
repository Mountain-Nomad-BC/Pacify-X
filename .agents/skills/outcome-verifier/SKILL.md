---
name: outcome-verifier
description: "Independently determine whether evidence, policy, and actual postconditions support the claimed result. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# outcome-verifier

## Purpose

Independently determine whether evidence, policy, and actual postconditions support the claimed result.

## Use when
- skill claims completion
- consequential recommendation produced
- memory candidate proposed

## Do not use when
- only executor conclusion is available without evidence

## Required inputs
- original goal
- approved plan
- evidence
- action trace
- policy
- postconditions
- proposed result

## Outputs
- verification status
- failed checks
- warnings
- required actions
- approved evidence

## Procedure
1. derive the required outcome and resolve its repository-owned postcondition contract.
2. resolve a signed, scoped policy decision; never accept a caller Boolean as policy authority.
3. resolve signed evidence references and verify integrity, signer, producer, freshness, and scope.
4. derive each postcondition result from the verified records.
5. identify unsupported inference.
6. return bounded status.

## Guardrails
- executor confidence is not proof.
- caller-provided `valid`, `current`, or `policy_allowed` fields are assertions, not authority.
- avoid persuasive internal narrative.
- policy violations cannot be argued away.

## Integration points
- outcome verifier
- intelligent system outcome monitor
- evidence store
- promotion gate

## Failure modes to test
- correlated context
- rubric drift
- rubber-stamping

## Operational metrics
- false pass
- false escalation
- human correction
- unsupported claims found

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [One Human, N Agents: Audit-Budget Allocation](https://arxiv.org/abs/2607.28317)
- [NiCE AI Agents for Enterprise CX](https://www.nice.com/lps/ai-agents-for-enterprise-cx)

## Runtime binding

- Family: `delegated`
- Binding: `runtime/outcome_verifier.py`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
