---
canonical_id: "studiolaunch"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Detached Studio request and observer launch

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Spawns an owned session worker, registers and signs its request, starts a terminal observer and waits for durable state change.

## Historical source state

Worker/request/observer resource identities and accepted state response.

## Limits and unknowns

Worker starts before request publication; no shared compensation encloses later request/sign/observer failure. Any state change qualifies for accepted/live_worker_observed, including failed. Full environment is inherited; stdout/stderr discarded.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3175]] — changed-file

## Directed relationships

- [[Systems/studiosession]] — publishes signed request after process creation (`E430`)
- [[Systems/terminalobserver]] — starts independent registered finalizer (`E431`)
- [[Systems/resourcecustody]] — starts child then records ownership (`E443`)
