---
canonical_id: "studioapprovaldispatch"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Host proof consumption before Studio mutation

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Consumes payload-bound single-use approval then replaces caller payload with signed data.

## Historical source state

Authenticated payload and approver passed to controller.

## Limits and unknowns

Consumption precedes later validation; direct helper callers have a different boundary.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3107]] — changed-file

## Directed relationships

- [[Systems/studioauthority]] — consumes exact host operation proof (`E871`)
- [[Systems/studiodraftdispatch]] — passes approved payload to draft owner (`E872`)
