---
canonical_id: "cogassurance"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Cognitive trust and behavioral probes

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Evaluates memory trust from explicit checks, executes supplied golden-benchmark callbacks and checks claim-to-current-evidence membership.

## Historical source state

Trust decision, actual/expected output hashes, benchmark denominator and unsupported claim IDs.

## Limits and unknowns

Trust/reality checks do not resolve signed evidence themselves. Golden benchmarks execute the supplied runner and assess exact/contains outputs.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1860]] — changed-file
- [[Evidence/S1861]] — changed-file
- [[Evidence/S1864]] — changed-file

## Directed relationships

- [[Systems/comparison]] — can supply benchmark outcome evidence (`E170`)
- [[Systems/cognitivetrustflags]] — exposes separately called assurance helper (`E712`)
- [[Systems/cognitiveidentitydrift]] — exposes separately called assurance helper (`E713`)
- [[Systems/goldencallback]] — exposes separately called assurance helper (`E714`)
- [[Systems/cognitivepassport]] — exposes separately called assurance helper (`E715`)
- [[Systems/cognitiveblackbox]] — exposes separately called assurance helper (`E716`)
- [[Systems/realitymembership]] — exposes separately called assurance helper (`E717`)
