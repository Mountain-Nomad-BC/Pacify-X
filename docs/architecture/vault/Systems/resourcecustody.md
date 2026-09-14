---
canonical_id: "resourcecustody"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Path and process custody ledger

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Registers resources, serializes ledger replacement and compares persisted PID/start identity for detached exit observation.

## Historical source state

Ownership, active/status flags, parent IDs, process handles and kernel start fingerprints where available.

## Limits and unknowns

Spawn precedes registration without compensation here. Self-completion closes custody before physical exit; parent poll alone underlies the generic process_tree_terminated label.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2980]] — changed-file
- [[Evidence/S2974]] — changed-file

## Directed relationships

- [[Systems/resourcereclaim]] — supplies registered identity and dependency flags (`E445`)
- [[Systems/filelease]] — serializes resource ledger reads and updates (`E459`)
