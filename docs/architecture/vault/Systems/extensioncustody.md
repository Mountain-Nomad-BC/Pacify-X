---
canonical_id: "extensioncustody"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Extension lifecycle and rollback custody

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Previews exact extension operations, retains rollback identity before uninstall, delegates native commands and consumes rollback custody only after exact-version observation.

## Historical source state

Expiring preview, prior identity, native command receipt, pending reload or reconciled state.

## Limits and unknowns

Enable/disable is a native-manager handoff. Retaining an old version identity does not ensure its installable bytes remain available.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1136]] — same-file-bytes
- [[Evidence/S1138]] — same-file-bytes
- [[Evidence/S1072]] — changed-file
- [[Evidence/S1134]] — same-file-bytes
- [[Evidence/S1141]] — same-file-bytes

## Directed relationships

- [[Systems/host]] — hands enablement to native manager (`E293`)
