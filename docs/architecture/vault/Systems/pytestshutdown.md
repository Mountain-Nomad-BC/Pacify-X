---
canonical_id: "pytestshutdown"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Pytest non-daemon thread shutdown observation

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Records initial live non-daemon thread object IDs and fails the session if new live threads remain.

## Historical source state

Session exit status and terminal leak description.

## Limits and unknowns

Does not join or terminate leaked threads, inspect subprocesses, or prove eventual process shutdown.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4064]] — same-file-bytes
- [[Evidence/S4063]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
