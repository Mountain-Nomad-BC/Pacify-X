---
canonical_id: "ui"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# VS Code dashboard and Studios

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Presents projects, agents, workflows, memory, knowledge and controls; sends typed host messages and renders refreshed projections.

## Historical source state

Webview state, request IDs and projected lifecycle status.

## Limits and unknowns

Rendered controls and installed interaction proof are different from backend declarations.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S992]] — changed-file
- [[Evidence/S1339]] — same-file-bytes
- [[Evidence/S1334]] — same-file-bytes
- [[Evidence/S1338]] — same-file-bytes

## Directed relationships

- [[Systems/bridge]] — dispatches typed requests (`E002`)
- [[Systems/activation]] — owns extension activation rollback (`E175`)
- [[Systems/memorylease]] — starts canonical lease controller (`E176`)
- [[Systems/environment]] — runs governed environment discovery (`E181`)
- [[Systems/draftcommit]] — sends validated create request with origin binding (`E222`)
- [[Systems/sidebarstate]] — validates and publishes sidebar snapshots (`E286`)
- [[Systems/workflowtrace]] — supplies current editor and run identity (`E290`)
- [[Systems/extensioncustody]] — creates native lifecycle command adapter (`E292`)
- [[Systems/cleanupstaging]] — dispatches approved selected cache disposition (`E294`)
- [[Systems/activityledger]] — records attributed host activity (`E299`)
- [[Systems/listenerhealth]] — builds attestation and updates listener result (`E300`)
- [[Systems/studiostarter]] — runs the starter sequence through bridge (`E302`)
- [[Systems/enterprisecontrol]] — dispatches enterprise readiness mutation (`E305`)
- [[Systems/mcplaunch]] — registers a host-started stdio definition (`E327`)
- [[Systems/enterprisecontrol]] — projects enterprise with persistence disabled (`E332`)
- [[Systems/webviewmodules]] — loads module scripts in declared order (`E336`)
- [[Systems/teaminventoryworker]] — runs team inventory under host governor and worker deadline (`E368`)
- [[Systems/envworker]] — starts generation-specific governed discovery (`E370`)
- [[Systems/envread]] — queries retained subject and detail rows (`E375`)
- [[Systems/canonicallease]] — ensures lease at startup timer and before snapshot (`E381`)
- [[Systems/contextobserve]] — collects host context before snapshot presentation (`E384`)
