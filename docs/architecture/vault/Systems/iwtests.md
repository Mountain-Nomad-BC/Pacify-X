---
canonical_id: "iwtests"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Installed walker declared test coverage

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Tests predicates, callback DOM fixtures, source patterns and selected spawned workers.

## Historical source state

Declared regression coverage; no product tests run in this audit.

## Limits and unknowns

Most orchestration guarantees use source regex; narrow behavioral tests do not prove full installed execution.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1436]] — same-file-bytes

## Directed relationships

- [[Systems/iwmerge]] — tests single-application stage behavior (`E1609`)
- [[Systems/iwpluginconfirm]] — tests callback identity substitution rejection (`E1610`)
- [[Systems/iwtimeout]] — tests timeout latch and explicit reset (`E1611`)
