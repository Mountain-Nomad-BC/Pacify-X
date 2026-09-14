---
canonical_id: "sidebarproviders"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Sidebar provider telemetry projection and display

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Classifies supplied provider freshness, usage, billing/fallback flags and carousel priority.

## Historical source state

Twelve provider rows and billing/usage presentation.

## Limits and unknowns

Telemetry absence is not proof of no billable activity; future timestamps and stale-only subsystem health need distinction.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1220]] — same-file-bytes
- [[Evidence/S461]] — same-file-bytes

## Directed relationships

- [[Systems/sidebarrender]] — renders provider carousel and billing labels (`E1017`)
