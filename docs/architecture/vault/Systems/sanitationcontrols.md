---
canonical_id: "sanitationcontrols"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Sanitation gate composition

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Builds a bounded primary corpus for email/binary review, combines supplied identifier/license results and invokes a separate credential scan.

## Historical source state

Per-gate status, primary corpus hash, findings, exclusions and aggregate validity.

## Limits and unknowns

Primary walker limits are 30,000 files, depth 80 and 2 GiB. The separate secret scan receives root, not the bounded file list, so its work is not constrained by those same limits or exact corpus.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2995]] — changed-file
- [[Evidence/S2844]] — changed-file

## Directed relationships

- [[Systems/walklimits]] — bounds its primary file corpus (`E359`)
- [[Systems/secretshapes]] — starts a separate root-based credential scan (`E360`)
