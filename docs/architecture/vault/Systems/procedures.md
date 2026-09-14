---
canonical_id: "procedures"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Host-interpreted native procedures

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Selected native skill bodies tell the host how to collect evidence, invoke named kernels, inspect outputs and hand candidate artifacts to separate admission owners.

## Historical source state

Hydrated procedure text, caller-created source records, candidate artifacts and review evidence.

## Limits and unknowns

An active procedural package can coordinate work through the host without a Python loop. Reading its instructions does not prove a host followed them or grant undeclared effects.

## Historical suggested evolution

Host execution can construct candidates that later pass independent promotion and change discoverability.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2441]] — changed-file
- [[Evidence/S218]] — same-file-bytes
- [[Evidence/S144]] — same-file-bytes
- [[Evidence/S148]] — same-file-bytes

## Directed relationships

- [[Systems/research]] — prescribes source extraction and typed validation (`E209`)
- [[Systems/foundry]] — prescribes compilation and candidate certification (`E210`)
- [[Systems/refinery]] — prescribes novelty review and staged merges (`E211`)
- [[Systems/admission]] — hands reviewed candidates to separate admission (`E212`)
- [[Systems/vault]] — prescribes project lease and memory lifecycle commands (`E243`)
- [[Systems/metacognition]] — selects one reasoning contract and bounded operation (`E244`)
- [[Systems/crosswalk]] — prescribes fingerprinted mechanism comparison (`E245`)
- [[Systems/primitives]] — orders scope effects work verification and commit (`E246`)
- [[Systems/hybridadapter]] — selects retrieval contract and helper interface (`E247`)
- [[Systems/traceprocedure]] — selects the active trace compilation workflow (`E248`)
- [[Systems/candidatepipeline]] — prescribes staged candidate evaluation (`E278`)
- [[Systems/facttime]] — prescribes temporal query and invalidation (`E279`)
- [[Systems/offlinecandidate]] — prescribes isolated candidate comparison (`E280`)
- [[Systems/workdecision]] — prescribes budget and work decisions (`E281`)
- [[Systems/n8nprocedures]] — selects workflow-specific host procedure (`E296`)
- [[Systems/supabaseprocedures]] — selects data-platform host procedure (`E297`)
