---
canonical_id: "supervisebudget"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Process capture time and disk controls

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Authorizes supplied action and limits, retains bounded output prefixes, polls startup/idle/total time and sampled disk growth.

## Historical source state

Decoded output/counters, control status and sanitized receipt.

## Limits and unknowns

Capture limits drop excess bytes without stopping producer. Setup and baseline disk traversal precede supervision clock. Disk scans lack traversal deadline and skip read errors; optional paths otherwise whole-volume delta.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2618]] — changed-file
- [[Evidence/S2625]] — changed-file
- [[Evidence/S2624]] — changed-file

## Directed relationships

- [[Systems/resourcecustody]] — spawns and registers before main supervision (`E450`)
- [[Systems/supervisionclose]] — requests shutdown after terminal controls (`E451`)
