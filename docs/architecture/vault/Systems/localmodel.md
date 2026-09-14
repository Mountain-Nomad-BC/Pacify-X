---
canonical_id: "localmodel"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Local model admission and server lifecycle

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Inspects bounded GGUF metadata and binds model file identity before planning and supervising a local server.

## Historical source state

Model admission, server plan and supervised run state.

## Limits and unknowns

Model support in the code does not establish that a particular server is running in the current environment.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2348]] — changed-file
- [[Evidence/S2336]] — changed-file

## Directed relationships

- [[Systems/supervisor]] — runs admitted server under ownership (`E120`)
- [[Systems/ggufadmission]] — offers explicit model inspection (`E518`)
