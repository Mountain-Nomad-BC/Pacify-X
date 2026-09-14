---
canonical_id: "domaintemplatebridge"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Projected declared-domain command wrapper

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Prefers installed engineering_bootstrap owner and falls back to repository runtime, then loads JSON and invokes run_script_outcome.

## Historical source state

Printed outcome and validity-based exit0/1.

## Limits and unknowns

Fallback catches any ModuleNotFoundError from the imports; template executes at import and assumes its projected directory depth.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4055]] — changed-file
- [[Evidence/S2205]] — same-file-bytes

## Directed relationships

- [[Systems/declared]] — invokes declared runtime outcome (`E1406`)
