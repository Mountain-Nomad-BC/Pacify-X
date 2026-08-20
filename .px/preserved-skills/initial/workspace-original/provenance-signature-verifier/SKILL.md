---
name: provenance-signature-verifier
description: "Verify package identity, source, signature, hash, build chain, and owner. Use when the task requires this bounded operational control; keep it inactive otherwise."
---

# provenance-signature-verifier

## Purpose

Verify package identity, source, signature, hash, build chain, and owner.

## Use when
- skill/model adapter/workflow/policy loads

## Do not use when
- never bypass production

## Required inputs
- package
- signature
- hash
- source metadata
- trusted keys
- attestation

## Outputs
- verified/unverified
- owner
- integrity findings
- trust level

## Procedure
1. hash content.
2. verify signature.
3. verify source/owner.
4. check revocation/version.
5. record attestation.
6. bind release evidence to the exact packaged artifact, source snapshot, dependency lock, generated registry set, validation transcript, and configuration schema.
7. verify that every claimed tool actually executed and that blocked, skipped, and failed tools remain represented in the signed denominator.

## Guardrails
- filename is not identity.
- revoked keys fail closed.
- unsigned drafts stay non-production.
- a signature over an incomplete or misrepresented evidence set does not certify the release.

## Integration points
- registry
- admission
- deployment

## Failure modes to test
- key management failure
- trusted signer compromise

## Operational metrics
- unverified blocks
- hash mismatches

## Completion requirements

The skill is complete only when structured outputs are emitted, evidence references resolve, declared postconditions are checked, and the execution wrapper records the result. Any memory remains a candidate until framework promotion controls accept it.

## Research basis
- [Malicious Agent Skills in the Wild](https://arxiv.org/abs/2602.06547)

## Runtime binding

- Family: `supply_chain`
- Binding: `runtime.operational_controls.run_control`
- Activation: metadata is discoverable at startup; load this body only after selection.
- Effects: read-only control-plane analysis unless a separately admitted composed capability declares more.

## Completion and evidence

Return a structured decision, reasons, outputs, and evidence references. Treat unresolved provenance, permissions, required inputs, or postconditions as a fail-closed result. Candidate memory, research, generated skills, and speculative work never become active without separate admission and evidence.
