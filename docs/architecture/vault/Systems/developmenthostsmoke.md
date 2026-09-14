---
canonical_id: "developmenthostsmoke"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Development-source host smoke owner

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Prepares a fixture workspace and runs the source extension in a pinned test-electron host.

## Historical source state

Portable retained receipt and lifecycle evidence.

## Limits and unknowns

May download cache; setup precedes lease/try; successful receipt does not verify workspace reclamation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S787]] — same-file-bytes

## Directed relationships

- [[Systems/hostworkspacecustody]] — allocates and marks before lease (`E1451`)
- [[Systems/hostworkerclosure]] — awaits owned child (`E1453`)
- [[Systems/hostcachecustody]] — ensures cache marker before host (`E1457`)
