---
canonical_id: "canonicallease"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Host canonical workspace lease maintenance

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Starts periodic lease maintenance and calls bridge current/list/activation/renewal before visible dashboard snapshots.

## Historical source state

Attached/detached/degraded state, canonical project ID and expiry.

## Limits and unknowns

Uses shared session vscode-dashboard. A current lease is accepted without comparing requested projectRoot; fallback prioritizes a unique active project before basename matching. Stop clears timer but does not cancel pending work.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S903]] — same-file-bytes
- [[Evidence/S1198]] — same-file-bytes
- [[Evidence/S1093]] — changed-file
- [[Evidence/S1107]] — changed-file

## Directed relationships

- [[Systems/bridge]] — calls canonical current selection activation and renewal (`E382`)
