---
canonical_id: "sidebarhost"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Sidebar VS Code view and snapshot owner

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Registers webview, builds strict snapshots and routes refresh/navigation callbacks.

## Historical source state

Host-side current snapshot, envelope and listeners.

## Limits and unknowns

Projection/delivery/acknowledgement are distinct states; listener and async failure paths require care.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1233]] — same-file-bytes
- [[Evidence/S1090]] — changed-file

## Directed relationships

- [[Systems/sidebarprojectcalc]] — builds projection before outbound validation (`E1007`)
- [[Systems/sidebarprotocol]] — validates inbound and outbound envelopes (`E1009`)
- [[Systems/sidebarrender]] — posts validated snapshot to webview (`E1010`)
- [[Systems/sidebarprefs]] — awaits stored preferences before host republish (`E1012`)
- [[Systems/sidebarack]] — accepts equal-revision acknowledgement and inspects it (`E1015`)
- [[Systems/dashboardcontroller]] — opens control plane entity route and selected record (`E1016`)
