---
canonical_id: "workspacepayload"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Workspace JSON payload and idempotency owner

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Materializes paths and transfer evidence, checks effects/lease, executes stream and writes request receipt.

## Historical source state

Preview or stream result receipt/replay.

## Limits and unknowns

Preview skips payload checks; receipt appears after handler. Quarantine/recovery root contract differs from callee.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3321]] — changed-file
- [[Evidence/S3340]] — changed-file

## Directed relationships

- [[Systems/workspaceprojection]] — requires current project session (`E581`)
- [[Systems/streamdispatch]] — dispatches materialized operation (`E582`)
- [[Systems/transferbinding]] — binds paths to registered source and active destination (`E583`)
- [[Systems/quarantinetxn]] — supplies incompatible default transaction location (`E584`)
- [[Systems/recoverytxn]] — supplies incompatible default recovery location (`E585`)
