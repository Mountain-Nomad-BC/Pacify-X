---
canonical_id: "hostworkerclosure"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Host worker timeout and process closure

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Runs an owned Node worker, captures tails, requests termination and reconciles token-matching processes.

## Historical source state

Lifecycle receipt and bounded output tails.

## Limits and unknowns

Timeout followed by zero close can be completed; rejected/hung terminator can prevent settlement; no token reduces closure proof to worker exit.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S524]] — same-file-bytes

## Directed relationships

- [[Systems/hostgloballease]] — acquires or receives lease (`E1454`)
