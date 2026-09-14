---
canonical_id: "studioprotocol"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Import-time Studio operation vocabulary

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Selects source or packaged JSON and creates kind/operation sets.

## Historical source state

Process-local accepted operation vocabulary.

## Limits and unknowns

Malformed list entries are stringified; non-list kinds omitted; no handler-denominator proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3142]] — same-file-bytes

## Directed relationships

- [[Systems/studiotransport]] — sets argparse operation choices (`E869`)
