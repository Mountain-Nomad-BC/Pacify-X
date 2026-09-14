---
canonical_id: "workspaceprojection"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Workspace seals and lifecycle projections

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Checks config/registry seals and reconstructs session state from lifecycle events.

## Historical source state

Verified declarations and session projections.

## Limits and unknowns

Registry bytes and hash are separate reads; repeated session validation scans full history.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3318]] — changed-file
- [[Evidence/S3319]] — changed-file
- [[Evidence/S3328]] — changed-file

## Directed relationships

- [[Systems/workspaceevents]] — replays and validates session ancestry (`E577`)
