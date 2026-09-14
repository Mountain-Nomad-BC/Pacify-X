---
canonical_id: "manualextensioninstall"
kind: system
layer: release
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# PowerShell extension install and uninstall

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Resolves versioned VSIX, verifies a local hash-manifest entry and calls the code CLI.

## Historical source state

CLI status and installed-version observation.

## Limits and unknowns

Manifest is not authenticated; same-version replacement blocked but downgrade allowed; no installed-byte verification or rollback.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S299]] — same-file-bytes
- [[Evidence/S301]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
