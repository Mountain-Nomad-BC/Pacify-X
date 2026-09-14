---
canonical_id: "routingfusion"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Independent source discovery and candidate fusion

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Runs metadata navigator per source, canonicalizes explicit supersession/token shadows and scores already-discovered candidates.

## Historical source state

Ranked selectable/discovery-only records and component scores.

## Limits and unknowns

Source convergence can count repeated metadata. Missing inputs are reported by navigator but omitted from fusion candidate. Graph proximity boosts existing candidates.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1670]] — changed-file
- [[Evidence/S1673]] — changed-file
- [[Evidence/S3025]] — same-file-bytes

## Directed relationships

- [[Systems/routingpackage]] — selects package from ranked candidates (`E501`)
