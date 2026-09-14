---
canonical_id: "verify"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Outcome verification

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Separates claim evaluation from authoritative verification against signed policy/postcondition evidence and an explicit outcome contract.

## Historical source state

VerificationDecision or authoritative outcome report.

## Limits and unknowns

The bounded orchestrator uses the compatibility evaluation path, not verify_authoritative.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2592]] — changed-file
- [[Evidence/S2591]] — changed-file

## Directed relationships

- [[Systems/countenvelopes]] — checks registry count ownership during release audit (`E529`)
