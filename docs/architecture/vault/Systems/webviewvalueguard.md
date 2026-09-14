---
canonical_id: "webviewvalueguard"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Webview JSON shape and operation field guard

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Checks message shapes, limits, allowed fields and selected operation payloads.

## Historical source state

Accepted original message or validation refusal.

## Limits and unknowns

Allowed fields are not complete operation schemas or execution authority.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1339]] — same-file-bytes

## Directed relationships

- [[Systems/webviewdraftstate]] — validates persisted view-state envelope (`E1079`)
- [[Systems/studiohostcreate]] — allows creation envelope to independent host owner (`E1080`)
- [[Systems/extensionpreviewtokens]] — allows lifecycle message to host preview owner (`E1081`)
