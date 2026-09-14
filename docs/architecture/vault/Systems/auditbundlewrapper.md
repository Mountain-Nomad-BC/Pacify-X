---
canonical_id: "auditbundlewrapper"
kind: system
layer: release
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# PowerShell clean audit export wrapper

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Binds requested version and VSIX path, runs clean_source_export and emits archive SHA sidecar.

## Historical source state

Archive locator, SHA256 and wrapper valid flag.

## Limits and unknowns

No wrapper timeout or direct verification beyond child exit/archive hash; child owns governed export semantics.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S473]] — same-file-bytes

## Directed relationships

- [[Systems/exportrebuild]] — invokes clean source export owner (`E1485`)
