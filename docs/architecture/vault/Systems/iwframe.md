---
canonical_id: "iwframe"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Workbench and webview identity resolution

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Finds visible extension shells, reacquires content and restarts owned views.

## Historical source state

Frame handles, DOM identity and time-origin comparison.

## Limits and unknowns

Labels and selectors do not independently prove process identity; cached visibility and late effects can diverge.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S781]] — changed-file
- [[Evidence/S711]] — changed-file
- [[Evidence/S717]] — changed-file

## Directed relationships

- [[Systems/iwpalette]] — reopens dashboard through owned UI (`E1567`)
