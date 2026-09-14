---
canonical_id: "extensionstartupclaims"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Activation registration lifecycle and startup counters

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Registers sidebar, listeners, commands, chat/model/MCP providers and commits subscription transaction.

## Historical source state

Startup duration and registration-only declared counters.

## Limits and unknowns

Zero subprocess/write counters are constants, not instrumentation; resource creation can precede transaction ownership.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1086]] — changed-file
- [[Evidence/S1049]] — changed-file

## Directed relationships

- [[Systems/extensionmcpdefinition]] — registers lazy definition provider (`E1500`)
- [[Systems/extensionpanelreadiness]] — registers panel serializer and commands (`E1501`)
- [[Systems/chatparticipant]] — registers chat participant (`E1503`)
