---
canonical_id: "extensioncacheinventory"
kind: system
layer: scope
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Extension cache inventory and eligibility

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Binds root/file identity, rejects links and hard links, hashes candidate trees and retains host-only directory identity.

## Historical source state

Size-sorted candidate list with hashes and private identity fields.

## Limits and unknowns

Classifies by cache basename; exclusions differ from canonical Python custody, and candidate errors are silently omitted. No hard total byte/time bound inside inventory.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S928]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
