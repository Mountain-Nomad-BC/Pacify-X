---
canonical_id: "studioeditorinput"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Portable text package normalization and framing

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Normalizes bounded file topology and hashes exact UTF-8 paths/content with length framing.

## Historical source state

Sorted files, per-file hashes and px.skill-tree/2 digest.

## Limits and unknowns

Requires native package core files except preserved-original reads; does not itself authenticate skill semantics.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1321]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
