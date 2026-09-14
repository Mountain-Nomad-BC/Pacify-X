---
canonical_id: "globalisolation"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Global skill relocation and recovery

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Snapshots, preserves and moves global skills before clearing installer discovery.

## Historical source state

Locked apply and phase journal.

## Limits and unknowns

Interrupted move and manifest effects can precede journal records.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2216]] — same-file-bytes

## Directed relationships

- [[Systems/nativebackupcustody]] — uses verified inventory copies (`E893`)
- [[Systems/globalreappearance]] — reconciles later live tree (`E894`)
- [[Systems/globalmanifestcustody]] — clears installer metadata (`E895`)
