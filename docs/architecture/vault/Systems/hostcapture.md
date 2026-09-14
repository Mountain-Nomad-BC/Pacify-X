---
canonical_id: "hostcapture"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Host JSON subprocess capture

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Runs no-shell subprocesses with bounded output and parses either JSON stdout or exact Studio conflict stderr on exit2.

## Historical source state

Parsed result or bounded failure/cancellation; separate validation output status.

## Limits and unknowns

captureJson settles on cancellation/timeout after requesting termination, without a descendant census. runValidation instead waits close/error and does not handle an already-aborted signal before starting.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1174]] — same-file-bytes
- [[Evidence/S1208]] — same-file-bytes
- [[Evidence/S1167]] — same-file-bytes

## Directed relationships

- [[Systems/pysnapshot]] — invokes runtime.dashboard_api snapshot (`E391`)
