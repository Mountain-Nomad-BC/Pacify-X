---
canonical_id: "hostmodel"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# VS Code model execution

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Runs selected VS Code language-model requests in the host and returns model identity, token counters, tool results and output to Agent Studio completion.

## Historical source state

Host model response, cancellation token, exact requested options and completion receipt.

## Limits and unknowns

This is a host-owned model route, distinct from Python ProviderInvocationGateway. Local Ollama currently rejects tool-bound agent routes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1012]] — changed-file
- [[Evidence/S1600]] — same-file-bytes
- [[Evidence/S1152]] — same-file-bytes

## Directed relationships

- [[Systems/agent]] — returns validated completion inputs (`E114`)
