---
canonical_id: "distributionbind"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Artifact record and source manifest binding

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks artifact record bytes/versions and optionally validates live or frozen manifest projections.

## Historical source state

Artifact-set result and archive-entry digests.

## Limits and unknowns

Manifest optional; source_product_digest is supplied label, not recomputed here.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2878]] — changed-file
- [[Evidence/S2894]] — changed-file
- [[Evidence/S2898]] — changed-file

## Directed relationships

- [[Systems/distributionmanifestcheck]] — checks optional frozen manifest consistency (`E1166`)
- [[Systems/distributionarchive]] — inspects wheel and sdist metadata/member hashes (`E1167`)
