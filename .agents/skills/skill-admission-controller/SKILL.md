---
name: skill-admission-controller
description: "Control whether a skill may enter registry, sandbox, canary, or production. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# skill-admission-controller

## Purpose

Control whether a skill may enter registry, sandbox, canary, or production.

## Use when
- skill imported/generated/modified/upgraded

## Do not use when
- never bypass production activation

## Required inputs
- package
- manifest
- provenance
- dependencies
- permissions
- tests
- signatures

## Outputs
- admit/restrict/quarantine/reject
- remediations
- allowed environment
- promotion state

## Procedure
1. validate structure and resolve signed evidence references.
2. verify record signatures, producers, source/hash, freshness, and candidate/project scope.
3. diff permissions/effects.
4. scan prompt/code/dependencies.
5. detonate.
6. run tests/replay.
7. assign state.

## Guardrails
- unknown/unsigned remains quarantined.
- caller-provided provenance, licensing, test, and security Booleans cannot admit a candidate.
- declared effects must match observed.
- self-modifying eval prohibited.

## Integration points
- intelligent system registry
- detonator
- permission diff
- CI/CD

## Failure modes to test
- trusts manifest
- dependency behavior missed

## Operational metrics
- malicious escapes
- false rejection
- admission time

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Malicious Agent Skills in the Wild](https://arxiv.org/abs/2602.06547)
- [SkillDetonate: Dynamic Analysis for Agent Skills](https://arxiv.org/abs/2607.02357)

## Runtime binding

- Family: `delegated`
- Binding: `runtime/admission_controller.py`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.

For a changed skill, certify the observable behavioral delta with `runtime.behavioral_certification.certify_behavioral_delta`. Bind baseline, candidate, and case evidence hashes; include positive decisions, negative triggers, and hard gates; reject missing current evidence or fail-open gate behavior. Do not collect or compare private reasoning traces.
