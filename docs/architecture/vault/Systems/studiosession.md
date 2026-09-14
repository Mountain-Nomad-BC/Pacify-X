---
canonical_id: "studiosession"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Detached Studio session worker

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Verifies signed launch binding, rebinds its PID, reclaims request content and publishes cleanup binding before Agent/Workflow execution with deferred terminal state.

## Historical source state

Signed cleanup handoff and finalizing state before immediate subprocess exit.

## Limits and unknowns

BaseException attempts failed finalizing state; dual diagnostic storage failure falls back to stderr which launcher discards. Agent branch passes admitted request metadata to controller without fresh _admitted_context.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3158]] — same-file-bytes

## Directed relationships

- [[Systems/agentworkerpublication]] — invokes controller with deferred terminal publication (`E432`)
- [[Systems/terminalobserver]] — publishes cleanup binding then exits after finalizing (`E434`)
