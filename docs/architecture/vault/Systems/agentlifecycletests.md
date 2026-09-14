---
canonical_id: "agentlifecycletests"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Agent immutable revision and owned lifecycle fixtures

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Exercises creation replay, admission authentication, deterministic worker invocation, host completion envelopes and autonomous lifecycle observation.

## Historical source state

Tamper rejection, owned process state and supplied host-result assertions.

## Limits and unknowns

Host model results are supplied fixtures; worker execution is explicitly model_invoked=false. No tests executed here.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4080]] — same-file-bytes

## Directed relationships

- [[Systems/agentpreflight]] — tests immutable replay and signed admission rejection (`E1422`)
- [[Systems/localworker]] — defines real closed worker lifecycle fixtures (`E1423`)
- [[Systems/agenthostcompletion]] — supplies host model completion envelopes (`E1424`)
- [[Systems/agentworkerpublication]] — injects diagnostic publication failures (`E1425`)
