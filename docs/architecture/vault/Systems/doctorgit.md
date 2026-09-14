---
canonical_id: "doctorgit"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Doctor Git metadata observations

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Reads repository/head/branch/status and untracked names through bounded-wait Git commands.

## Historical source state

Dirty counts and Git section.

## Limits and unknowns

Output byte limits follow capture; ignored files and broader effects are outside observation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2740]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
