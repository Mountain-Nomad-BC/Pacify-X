---
name: human-handoff-state-transfer
description: "Transfer complete resumable operational state to a human or bounded agent. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# human-handoff-state-transfer

## Purpose

Transfer complete resumable operational state to a human or bounded agent.

## Use when
- approval required
- system blocked
- risk exceeds autonomy
- ownership changes

## Do not use when
- normal response needs no resumable work

## Required inputs
- goal
- state
- actions
- tool results
- evidence
- approvals
- unresolved items
- risks
- checkpoint

## Outputs
- handoff packet
- resume token
- next action
- ownership event

## Procedure
1. collect machine state.
2. separate facts/hypotheses.
3. include exact results.
4. record decisions/permissions.
5. identify unresolved risks.
6. create checkpoint.

## Guardrails
- prose summary alone is insufficient.
- scope secrets.
- do not claim completion before verification.

## Integration points
- session store
- intelligent system UI
- approval system
- outcome verifier

## Failure modes to test
- omitted state
- mutated checkpoint
- ambiguous owner

## Operational metrics
- resume success
- missing-state corrections
- handoff time
- human rework

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [NiCE AI Agents for Enterprise CX](https://www.nice.com/lps/ai-agents-for-enterprise-cx)
- [Graph-Based Agentic AI with LangGraph](https://arxiv.org/abs/2607.19297)

## Runtime binding

- Family: `progress`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
