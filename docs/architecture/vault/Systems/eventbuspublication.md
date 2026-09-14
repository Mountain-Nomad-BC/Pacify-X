---
canonical_id: "eventbuspublication"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Operational bus WAL publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Validates source route/tier and current previous hash, then commits event, receipt, state, head, anchor and projection.

## Historical source state

Ordered event envelope and transactional receipt.

## Limits and unknowns

Route cache uses file stat identity; event ID has no uniqueness or path-safe constraint beyond nonempty string.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2477]] — changed-file

## Directed relationships

- [[Systems/routedeclarations]] — checks registered route ID and matching tier (`E752`)
- [[Systems/wal]] — commits six canonical artifacts (`E753`)
- [[Systems/eventbushead]] — publishes current state and hash anchor (`E754`)
- [[Systems/eventbusreplay]] — appends envelopes for full ancestry scan (`E755`)
- [[Systems/eventbuswait]] — notifies this instance after commit (`E756`)
