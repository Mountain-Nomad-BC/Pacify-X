---
canonical_id: "extensionfixturecontracts"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Extension package and host fixture assertions

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks package text contracts, fixture determinism and selected mocked host lifecycle cases.

## Historical source state

Source assertions; tests not run in this audit.

## Limits and unknowns

Regex presence is weaker than command registration or behavioral execution; host mocks omit confirmed lease/timeout cases.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1447]] — changed-file
- [[Evidence/S1448]] — same-file-bytes
- [[Evidence/S1445]] — same-file-bytes
- [[Evidence/S1419]] — same-file-bytes

## Directed relationships

- [[Systems/hostgloballease]] — tests active and one stale lock (`E1460`)
- [[Systems/hostworkerclosure]] — tests fake close and timeout outcomes (`E1461`)
- [[Systems/pluginfixturebuilder]] — builds twice and compares hashes (`E1462`)
- [[Systems/manualextensioninstall]] — checks installer source patterns (`E1463`)
- [[Systems/installedsmokeparent]] — checks source identity guard strings (`E1464`)
