---
canonical_id: "certificationfreeze"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Certification frozen candidate and toolchain

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Checks prerequisites, locks release, materializes source, installs offline tools and builds once.

## Historical source state

Candidate, artifacts and external quarantine.

## Limits and unknowns

Initial Git/preflight captured before lock; quarantine lifecycle not registered here.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2861]] — changed-file

## Directed relationships

- [[Systems/releasefixturecopy]] — materializes staged classified inputs (`E841`)
- [[Systems/certificationsupplychain]] — records built subjects and source metadata (`E842`)
- [[Systems/certificationgates]] — invokes default or injected gate runner (`E843`)
