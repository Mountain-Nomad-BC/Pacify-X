---
canonical_id: "dashboardcontroller"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Dashboard controller and request matching

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Composes state and renderers, owns the actual VS Code message wrapper and receives typed host results.

## Historical source state

Outbound request identities, pending requests, host results and rendered views.

## Limits and unknowns

Consumer logic is route-specific: several results match pending request IDs; snapshot messages update projections directly. These anchored paths do not yet close every controller operation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S339]] — same-file-bytes
- [[Evidence/S363]] — same-file-bytes
- [[Evidence/S408]] — same-file-bytes
- [[Evidence/S1001]] — changed-file

## Directed relationships

- [[Systems/ui]] — posts host messages to schema-validated switch (`E338`)
- [[Systems/dashboardhealth]] — derives rendered connection and certification state (`E339`)
- [[Systems/surfacecore]] — dispatches supplied snapshot and helper context (`E989`)
- [[Systems/surfacecatalog]] — dispatches supplied snapshot and helper context (`E991`)
- [[Systems/surfaceoperational]] — dispatches supplied snapshot and helper context (`E993`)
- [[Systems/surfacesystem]] — dispatches supplied snapshot and helper context (`E995`)
- [[Systems/surfaceobservability]] — dispatches supplied snapshot and helper context (`E997`)
- [[Systems/surfaceadvanced]] — dispatches supplied snapshot and helper context (`E999`)
- [[Systems/surfacegraph]] — dispatches supplied snapshot and helper context (`E1001`)
- [[Systems/studiohostcreate]] — submits create to origin-bound host coordinator (`E1023`)
- [[Systems/workfloweditnormalize]] — normalizes editable workflow and reopened catalog detail (`E1035`)
- [[Systems/workfloweditvalidate]] — validates current workflow draft (`E1036`)
- [[Systems/agenteditvalidate]] — normalizes and validates agent editor state (`E1038`)
- [[Systems/agenteditgraph]] — synchronizes graph and builds candidate payload (`E1039`)
- [[Systems/skilleditfiles]] — prepares native skill draft and synchronizes identity (`E1041`)
- [[Systems/editorhistory]] — records selected lifecycle response summary (`E1045`)
- [[Systems/extensionpreviewtokens]] — requests fresh lifecycle preview from routed conflict (`E1055`)
- [[Systems/workflowtracebrowser]] — applies browser-owned result projection (`E1070`)
- [[Systems/webviewvalueguard]] — sends messages validated before host dispatch (`E1078`)
- [[Systems/typedinventorybuilder]] — provides navigation array declarations (`E1286`)
