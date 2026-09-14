---
canonical_id: "installedsmokeparent"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Installed VSIX parent identity and receipts

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Prepares isolated settings and parent configuration, runs the worker and retains host/lifecycle evidence.

## Historical source state

Retained installed host receipt with VSIX and optional runtime identity.

## Limits and unknowns

Runtime marker schema/hash grammar is checked without recomputing tree hash; setup before lease can escape cleanup; terminal receipt can precede cleanup.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S589]] — same-file-bytes

## Directed relationships

- [[Systems/hostworkspacecustody]] — allocates and marks before lease (`E1450`)
- [[Systems/hostworkerclosure]] — awaits owned child (`E1452`)
- [[Systems/installedsmokechild]] — passes config to child (`E1455`)
