---
canonical_id: "pythonworkplane"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Persistent Python work admission and state bus

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Serializes same-operation work across processes, admits lane slots, joins matching newly published results and records causal domain revisions.

## Historical source state

Owner directories, result cache, state.json, recent50 outcomes, domain counters and orphaned lock custody.

## Limits and unknowns

Admission wait timeout does not interrupt producer execution. Cache reader does not verify result_sha256. Operation cache publication precedes finish-state commit; PID liveness is not creation-identity proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3277]] — changed-file
- [[Evidence/S4424]] — changed-file

## Directed relationships

- [[Systems/pyhardwarecache]] — executes or joins informational sensor producer (`E393`)
