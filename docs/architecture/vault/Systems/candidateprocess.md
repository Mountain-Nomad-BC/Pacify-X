---
canonical_id: "candidateprocess"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Candidate owned process execution

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Spawns ResourceManager owner, streams log and completes/terminates process under shared deadline.

## Historical source state

Resource IDs, exit/log and selected zero resource counters.

## Limits and unknowns

Other exception paths lack unconditional closure; resource valid flag not checked.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3981]] — changed-file

## Directed relationships

- [[Systems/releasestageowner]] — launches configured stage owner (`E919`)
- [[Systems/installedsummaryconsumer]] — checks downstream installed proof (`E920`)
- [[Systems/releasecampaignfinish]] — observes passed release-stage projection (`E923`)
