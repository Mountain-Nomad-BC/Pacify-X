---
canonical_id: "pytestentry"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Pytest plugin admission and shared-root guard

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Loads lifecycle hooks through root conftest or explicit runner plugin arguments.

## Historical source state

Per-session hooks and call-phase shared-base observation.

## Limits and unknowns

Shared-base repair checks directory existence only during test call, not full contents or every fixture phase.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S285]] — same-file-bytes
- [[Evidence/S4061]] — same-file-bytes
- [[Evidence/S4062]] — same-file-bytes
- [[Evidence/S3221]] — changed-file

## Directed relationships

- [[Systems/pytestreclaim]] — installs autouse teardown fixture (`E1397`)
- [[Systems/pytestshutdown]] — installs session start and finish hooks (`E1398`)
