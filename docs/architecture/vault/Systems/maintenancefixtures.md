---
canonical_id: "maintenancefixtures"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Maintenance source fixtures and coverage gaps

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Specifies cache custody, identifier scope, sanitizer collisions, secret review identity and extension disposal outcomes.

## Historical source state

Source assertions and synthetic filesystem cases; no tests executed.

## Limits and unknowns

Missing nested-cache placement, sanitizer symlink resolution, fallback ancestor substitution and post-effect receipt publication failures.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4112]] — same-file-bytes
- [[Evidence/S4374]] — same-file-bytes
- [[Evidence/S4373]] — same-file-bytes
- [[Evidence/S4371]] — same-file-bytes
- [[Evidence/S4375]] — same-file-bytes
- [[Evidence/S1374]] — same-file-bytes

## Directed relationships

- [[Systems/cachemovepublication]] — defines cache move and custody fixtures (`E1443`)
- [[Systems/sanitizerpreflight]] — defines preservation and collision fixtures (`E1444`)
- [[Systems/sanitationauditreader]] — checks pattern boundaries and explicit not-run gates (`E1445`)
- [[Systems/sanitationcontrols]] — supplies clean identifier and licensing fixtures (`E1446`)
- [[Systems/secretshapes]] — checks redacted shapes and stale review identity (`E1447`)
- [[Systems/extensioncleanupexecution]] — specifies staged disposition outcome handling (`E1448`)
- [[Systems/extensioncacheinventory]] — specifies link hardlink and evidence exclusion (`E1449`)
