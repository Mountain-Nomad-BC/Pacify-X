---
canonical_id: "distributionbuild"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# One-call wheel and sdist build helper

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Requires empty output, invokes build once, derives projections and checks produced archives.

## Historical source state

Build invocation count and artifact verification.

## Limits and unknowns

Once per call is distinct from campaign-wide exactly-once ownership.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2888]] — changed-file

## Directed relationships

- [[Systems/distributionprojection]] — generates manifest after backend build (`E1160`)
- [[Systems/distributionarchive]] — inspects produced artifacts through projection verifier (`E1162`)
- [[Systems/distributionintermediates]] — handles backend source-tree intermediate dependency (`E1163`)
