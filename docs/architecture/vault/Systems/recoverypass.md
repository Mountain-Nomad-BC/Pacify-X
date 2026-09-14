---
canonical_id: "recoverypass"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Configured authority reconciliation pass

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Inspects or applies configured WAL recovery and durable-state migrations, validates coordination startup and calls configured event/session/resource reconcilers.

## Historical source state

Per-component status, configured flags, retained forensic state and dry_run/apply mode.

## Limits and unknowns

Only configured targets/callbacks are covered. Empty callback groups can appear healthy with configured=False; overall healthy does not prove every runtime component was inspected.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2783]] — changed-file

## Directed relationships

- [[Systems/wal]] — chooses inspect or recover for configured journals (`E264`)
- [[Systems/recovery]] — validates or migrates configured durable state (`E265`)
- [[Systems/resources]] — calls supplied resource reconciliation callbacks (`E266`)
- [[Systems/durablestore]] — loads configured durable state (`E614`)
- [[Systems/durablemigration]] — migrates legacy state only on apply (`E615`)
- [[Systems/pycoordstartup]] — checks configured project coordination store (`E621`)
