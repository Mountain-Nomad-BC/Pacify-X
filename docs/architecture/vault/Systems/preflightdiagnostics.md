---
canonical_id: "preflightdiagnostics"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Dry-run discovery and named probe wrappers

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Selects preflight mode or individual diagnostics.

## Historical source state

Diagnostic result with signing/publication flags.

## Limits and unknowns

Dry-run can write projections/caches; mutation --probe choice is ignored.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2946]] — changed-file
- [[Evidence/S2945]] — changed-file
- [[Evidence/S3949]] — same-file-bytes

## Directed relationships

- [[Systems/preflightstatic]] — calls preflight with altered mode flags (`E839`)
