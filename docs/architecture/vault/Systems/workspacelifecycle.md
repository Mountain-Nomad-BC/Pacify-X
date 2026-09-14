---
canonical_id: "workspacelifecycle"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Workspace project activation switch and release

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Admits/checks projects, requires repair campaign state and records bounded session lifecycle.

## Historical source state

Lease/root bindings, switch checkpoints and project status.

## Limits and unknowns

Caller reset plus synthetic namespace denial does not measure host teardown; events and projections publish separately.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3329]] — changed-file
- [[Evidence/S3338]] — changed-file
- [[Evidence/S3342]] — changed-file

## Directed relationships

- [[Systems/workspaceprojection]] — loads sealed configuration and current session (`E578`)
- [[Systems/workspaceevents]] — appends intent revocation and creation events (`E579`)
- [[Systems/scopechecks]] — runs synthetic old-project access denial (`E580`)
- [[Systems/projectintegrity]] — requires project check before activation (`E598`)
