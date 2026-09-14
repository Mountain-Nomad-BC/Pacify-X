---
canonical_id: "catalog"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Capability and native skill catalogs

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Maintains discoverable capability metadata, native package identity, admission status, aliases and body pointers.

## Historical source state

Registry manifests, skill index and preserved package identity.

## Limits and unknowns

This vault models subsystem behavior, not every individual catalog entry.

## Historical suggested evolution

Admitted skill promotion updates discoverable projections; later queries can select the new revision.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2444]] — changed-file
- [[Evidence/S2441]] — changed-file
- [[Evidence/S2795]] — changed-file

## Directed relationships

- [[Systems/router]] — supplies canonical discovery records (`E022`)
- [[Systems/orchestrator]] — offers admitted capability metadata (`E027`)
- [[Systems/specialists]] — supplies bounded specialist metadata (`E116`)
- [[Systems/primitives]] — binds advertised functions to sole owners (`E192`)
- [[Systems/skillstatus]] — checks selectable package lifecycle (`E206`)
- [[Systems/assetpaths]] — resolves source and installed declarations (`E314`)
- [[Systems/nativeindexidentity]] — validates derived index denominator (`E880`)
- [[Systems/behaviormetadataplan]] — supplies owner IDs and tags for token matching (`E1358`)
- [[Systems/externalrequirementowners]] — supplies known owner ID set (`E1359`)
