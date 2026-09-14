---
canonical_id: "extensionsnapshot"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Composed dashboard snapshot and publication

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Joins canonical memory/bridge state with cached host context, environment, identity, validation and sidebar observations.

## Historical source state

Shared currentSnapshot and per-request webview publication.

## Limits and unknowns

Only bridge.snapshot failure is converted to disconnected; other component failures reject composition after partial global mutation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1108]] — changed-file

## Directed relationships

- [[Systems/extensioncontextcache]] — composes cached host context (`E1490`)
- [[Systems/extensionidentity]] — compares selected host/source assets (`E1491`)
- [[Systems/sidebarhost]] — pushes composed snapshot (`E1492`)
- [[Systems/dashboardqueryresponses]] — supplies composed browser snapshot (`E1521`)
